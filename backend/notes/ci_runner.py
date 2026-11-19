"""Kern CI: runners that execute one job and know nothing about Django or the database.

``ShellRunner``   runs the steps with bash in a temporary checkout on this machine (development, tests).
``DockerRunner``  talks to the Docker Engine API over its unix socket (standard library only). The
                  worker normally runs in a container itself, so a path of its own filesystem would
                  mean something else for the host's daemon: instead the workspace is copied into a
                  fresh container with ``PUT /containers/{id}/archive``, the steps run as execs, and the
                  artifacts are copied out with ``GET /containers/{id}/archive`` before the container
                  is removed.

Both implement :meth:`Runner.run`, which loops over the steps, enforces the timeouts, honours
cancellation and returns a :class:`JobOutcome`.
"""
from __future__ import annotations

import http.client
import json
import os
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from . import ci_pipeline as pl

WORKDIR = "workspace"
LABEL = "kern.ci"


class RunnerError(Exception):
    """The runner itself failed (not the job's steps)."""


@dataclass
class StepSpec:
    name: str
    script: str
    timeout: float | None = None  # seconds; None = the job's
    env: dict = field(default_factory=dict)


@dataclass
class JobSpec:
    name: str
    image: str
    env: dict  # everything the steps see: pipeline env, secrets and KERN_* variables
    steps: list[StepSpec]
    timeout: float  # seconds for the whole job
    artifacts: list[str] = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # attached to docker containers


@dataclass
class JobOutcome:
    status: str  # success | failed | cancelled | error
    exit_code: int | None = None
    note: str = ""
    artifacts: list[str] = field(default_factory=list)  # paths relative to the job's artifact folder


@dataclass
class ExecResult:
    code: int | None
    reason: str | None = None  # None | "timeout" | "cancelled"


def fmt_duration(s: float) -> str:
    if s >= 120:
        return f"{s / 60:g} min"
    return f"{s:.0f} s" if s >= 10 else f"{s:.1f} s"


# ------------------------------------------------------------------- logs


class LogWriter:
    """Appends job output to a file, replacing secret values with ``***``. A secret split across two
    writes is still caught: the last few bytes are held back until more output (or close) arrives."""

    def __init__(self, path: Path, secrets=(), max_bytes: int | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "ab", buffering=0)
        self.lock = threading.Lock()
        self.values: list[bytes] = []
        self.hold = 0
        self.set_secrets(secrets)
        self.buf = b""
        self.max = max_bytes if max_bytes is not None else int(float(os.environ.get("KERN_CI_MAX_LOG_MB", 20)) * 1024 * 1024)
        self.written = 0
        self.truncated = False
        self.at_nl = True

    def set_secrets(self, secrets):
        values = set()
        for s in secrets:
            if not s:
                continue
            values.add(s)
            if "\n" in s:  # multi-line secrets (keys): each line on its own
                values.update(x.strip() for x in s.splitlines() if len(x.strip()) >= 4)
        with self.lock:
            self.values = sorted((v.encode() for v in values if len(v) >= 3), key=len, reverse=True)
            self.hold = max((len(v) for v in self.values), default=1) - 1

    def _mask(self, b: bytes) -> bytes:
        for v in self.values:
            b = b.replace(v, b"***")
        return b

    def _emit(self, b: bytes):
        if self.truncated or not b:
            return
        if self.written + len(b) > self.max:
            b = b[: max(0, self.max - self.written)] + b"\n[kern-ci] log limit reached, the rest is dropped\n"
            self.truncated = True
        self.written += len(b)
        self.at_nl = b.endswith(b"\n")
        self.f.write(b)

    def write(self, data: bytes):
        with self.lock:
            if not self.values:
                return self._emit(data)
            masked = self._mask(self.buf + data)
            nl = masked.rfind(b"\n") + 1
            cut = max(nl, len(masked) - self.hold)
            self._emit(masked[:cut])
            self.buf = masked[cut:]

    def line(self, text: str):
        """A message from Kern itself (always starts on a fresh line)."""
        with self.lock:
            if self.buf:
                self._emit(self._mask(self.buf))
                self.buf = b""
        self.write(("" if self.at_nl else "\n").encode() + text.encode() + b"\n")

    def close(self):
        with self.lock:
            if self.buf:
                self._emit(self._mask(self.buf))
                self.buf = b""
            self.f.close()


# -------------------------------------------------------------- artifacts


class ArtifactSink:
    """Collects files whose workspace-relative path matches the globs into ``dest``."""

    def __init__(self, dest: Path, patterns: list[str], max_bytes: int | None = None):
        self.dest = Path(dest)
        self.patterns = [(p, pl.glob_regex(p.strip().strip("/").removeprefix("./"))) for p in patterns]
        self.hit = {p: 0 for p, _ in self.patterns}
        self.max = max_bytes if max_bytes is not None else int(float(os.environ.get("KERN_CI_MAX_ARTIFACT_MB", 500)) * 1024 * 1024)
        self.total = 0
        self.files: list[str] = []

    def wants(self, rel: str) -> bool:
        found = False
        for p, rx in self.patterns:
            if pl.matches_path(rx, rel):
                self.hit[p] += 1
                found = True
        return found

    def add(self, rel: str, src):
        """``src`` is a path or a binary file object."""
        parts = [x for x in rel.split("/") if x]
        if not parts or any(x in (".", "..") for x in parts):
            return
        rel = "/".join(parts)
        target = self.dest.joinpath(*parts)
        if self.total >= self.max:
            raise RunnerError(f"Artifacts are larger than {self.max // (1024 * 1024)} MB.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as out:
            if isinstance(src, (str, Path)):
                with open(src, "rb") as f:
                    shutil.copyfileobj(f, out)
            else:
                shutil.copyfileobj(src, out)
        self.total += target.stat().st_size
        if self.total > self.max:
            target.unlink(missing_ok=True)
            raise RunnerError(f"Artifacts are larger than {self.max // (1024 * 1024)} MB.")
        self.files.append(rel)

    def report(self, log: LogWriter):
        for p, n in self.hit.items():
            if not n:
                log.line(f"[kern-ci] artifact pattern {p!r} matched no files")
        if self.files:
            log.line(f"[kern-ci] collected {len(self.files)} artifact file(s)")


# ----------------------------------------------------------------- runner


class Runner:
    name = "base"

    # -- to implement
    def setup(self, job: JobSpec, checkout: Path, log: LogWriter): ...
    def exec(self, job: JobSpec, step: StepSpec, env: dict, timeout: float, log: LogWriter,
             cancelled: Callable[[], bool]) -> ExecResult: ...
    def collect(self, job: JobSpec, sink: ArtifactSink): ...
    def teardown(self): ...

    # -- shared
    def run(self, job: JobSpec, checkout: Path, log: LogWriter, cancelled: Callable[[], bool],
            artifacts_dir: Path) -> JobOutcome:
        started = time.monotonic()
        deadline = started + job.timeout
        total = len(job.steps)
        try:
            self.setup(job, checkout, log)
            for i, step in enumerate(job.steps, 1):
                if cancelled():
                    return JobOutcome("cancelled", note="cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.line(f"[kern-ci] job timed out after {fmt_duration(job.timeout)}")
                    return JobOutcome("failed", note=f"timed out after {fmt_duration(job.timeout)}")
                limit = min(step.timeout or job.timeout, remaining)
                log.line(f"##[step {i}/{total}] {step.name}")
                res = self.exec(job, step, job.env | step.env, limit, log, cancelled)
                if res.reason == "cancelled":
                    log.line("[kern-ci] cancelled")
                    return JobOutcome("cancelled", note="cancelled")
                if res.reason == "timeout":
                    job_wide = step.timeout is None or limit < step.timeout
                    what = "job" if job_wide else "step"
                    shown = job.timeout if job_wide else step.timeout
                    log.line(f"[kern-ci] {what} timed out after {fmt_duration(shown)}")
                    return JobOutcome("failed", exit_code=res.code, note=f"{what} timed out after {fmt_duration(shown)}")
                if res.code != 0:
                    log.line(f"[kern-ci] step {i} exited with code {res.code}")
                    return JobOutcome("failed", exit_code=res.code, note=f"step {i} failed (exit {res.code})")
            files: list[str] = []
            if job.artifacts:
                sink = ArtifactSink(artifacts_dir, job.artifacts)
                self.collect(job, sink)
                sink.report(log)
                files = sink.files
            return JobOutcome("success", exit_code=0, artifacts=files)
        except RunnerError as e:
            log.line(f"[kern-ci] error: {e}")
            return JobOutcome("error", note=str(e)[:290])
        finally:
            try:
                self.teardown()
            except Exception as e:  # noqa: BLE001
                log.line(f"[kern-ci] cleanup failed: {e}")


def _extract_tar(tar_path: Path, dest: Path):
    """Unpack a `git archive` tar; entries that would leave ``dest`` are skipped."""
    with tarfile.open(tar_path, "r") as tf:
        for m in tf:
            try:
                tarfile.data_filter(m, str(dest))
            except tarfile.FilterError:
                continue
            tf.extract(m, dest, filter="data")


# ------------------------------------------------------------------ shell


class ShellRunner(Runner):
    name = "shell"

    def __init__(self):
        self.tmp: Path | None = None

    def setup(self, job, checkout, log):
        self.tmp = Path(tempfile.mkdtemp(prefix="kern-ci-"))
        (self.tmp / "home").mkdir()
        _extract_tar(checkout, self.tmp)
        (self.tmp / WORKDIR).mkdir(exist_ok=True)
        if not shutil.which("bash"):
            raise RunnerError("bash is not installed on this machine.")

    @property
    def ws(self) -> Path:
        return self.tmp / WORKDIR

    def exec(self, job, step, env, timeout, log, cancelled):
        full = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp / "home"),
                "LANG": "C.UTF-8", "CI": "1", **env}
        try:
            p = subprocess.Popen(["bash", "-e", "-c", step.script], cwd=self.ws, env=full, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            raise RunnerError(f"Could not start bash: {e}")

        def pump():
            try:
                while chunk := os.read(p.stdout.fileno(), 65536):
                    log.write(chunk)
            except (OSError, ValueError):
                pass

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        reason = None
        while True:
            try:
                p.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled():
                reason = "cancelled"
            elif time.monotonic() >= deadline:
                reason = "timeout"
            if reason:
                self._kill(p)
                break
        t.join(5)
        self._kill(p, only_group=True)  # stray background processes of the step
        try:
            p.stdout.close()
        except OSError:
            pass
        return ExecResult(p.returncode, reason)

    @staticmethod
    def _kill(p, only_group=False):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            if only_group:
                break
            try:
                p.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                continue
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def collect(self, job, sink):
        base = str(self.ws)
        for dirpath, dirs, files in os.walk(base, followlinks=False):
            for f in files:
                full = os.path.join(dirpath, f)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                if sink.wants(rel):
                    sink.add(rel, full)

    def teardown(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None


# ----------------------------------------------------------------- docker


class DockerError(RunnerError):
    pass


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=60):
        super().__init__("docker", timeout=timeout)
        self.unix_path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.unix_path)
        except OSError as e:
            s.close()
            raise DockerError(f"Cannot reach Docker at {self.unix_path}: {e}")
        self.sock = s


def docker_socket() -> str:
    p = os.environ.get("KERN_DOCKER_SOCKET") or os.environ.get("DOCKER_HOST", "")
    if p.startswith("unix://"):
        p = p[len("unix://"):]
    return p or "/var/run/docker.sock"


class Demux:
    """Docker's multiplexed stream: 8-byte header (stream, 0, 0, 0, size) then the payload."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data
        while len(self.buf) >= 8:
            size = struct.unpack(">I", self.buf[4:8])[0]
            if len(self.buf) < 8 + size:
                break
            payload, self.buf = self.buf[8:8 + size], self.buf[8 + size:]
            yield payload


class DockerAPI:
    def __init__(self, sock_path: str | None = None):
        self.sock = sock_path or docker_socket()

    def call(self, method, path, body=None, headers=None, timeout=60, ok=(200, 201, 204)):
        conn = _UnixConnection(self.sock, timeout)
        h = dict(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            data = r.read()
        except (OSError, http.client.HTTPException) as e:
            raise DockerError(f"Docker request failed: {e}")
        finally:
            conn.close()
        if r.status not in ok:
            raise DockerError(f"Docker said {r.status} for {method} {path.split('?')[0]}: {_msg(data)}", ) from None
        return r.status, data

    def json(self, method, path, body=None, **kw):
        _, data = self.call(method, path, body, **kw)
        return json.loads(data) if data else None

    def ping(self):
        self.call("GET", "/_ping", timeout=5)

    def ensure_image(self, image: str, log: LogWriter):
        status = None
        try:
            self.call("GET", f"/images/{quote(image, safe='/:@')}/json", timeout=30)
            return
        except DockerError as e:
            if "said 404" not in str(e):
                raise
        log.line(f"[kern-ci] pulling image {image}")
        conn = _UnixConnection(self.sock, 600)
        try:
            conn.request("POST", f"/images/create?fromImage={quote(image, safe='')}")
            r = conn.getresponse()
            body = r.read()
        except (OSError, http.client.HTTPException) as e:
            raise DockerError(f"Could not pull {image}: {e}")
        finally:
            conn.close()
        if r.status != 200:
            raise DockerError(f"Could not pull {image}: {_msg(body)}")
        for line in body.splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if isinstance(j, dict) and j.get("error"):
                raise DockerError(f"Could not pull {image}: {j['error']}")

    def exec_stream(self, exec_id, on_data, timeout, cancelled) -> str | None:
        """Run an exec and feed its output to ``on_data`` until it ends. Returns None, "timeout" or
        "cancelled" (the caller then kills the container)."""
        body = json.dumps({"Detach": False, "Tty": False}).encode()
        req = (f"POST /exec/{exec_id}/start HTTP/1.1\r\nHost: docker\r\nContent-Type: application/json\r\n"
               f"Connection: Upgrade\r\nUpgrade: tcp\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        try:
            try:
                s.connect(self.sock)
                s.sendall(req)
                head = b""
                while b"\r\n\r\n" not in head:
                    chunk = s.recv(4096)
                    if not chunk:
                        raise DockerError("Docker closed the connection while starting a step.")
                    head += chunk
                    if len(head) > 65536:
                        raise DockerError("Unexpected response from Docker.")
            except OSError as e:
                raise DockerError(f"Docker request failed: {e}")
            head, _, rest = head.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            status = int(lines[0].split()[1]) if len(lines[0].split()) > 1 else 0
            if status not in (101, 200):
                raise DockerError(f"Docker said {status} starting a step: {_msg(rest)}")
            if any(x.lower().startswith("transfer-encoding") and "chunked" in x.lower() for x in lines[1:]):
                raise DockerError("Docker answered with a chunked stream, which is not supported.")
            demux = Demux()
            deadline = time.monotonic() + timeout
            if rest:
                for p in demux.feed(rest):
                    on_data(p)
            while True:
                if cancelled():
                    return "cancelled"
                if time.monotonic() >= deadline:
                    return "timeout"
                ready, _, _ = select.select([s], [], [], 0.3)
                if not ready:
                    continue
                try:
                    data = s.recv(65536)
                except OSError:
                    data = b""
                if not data:
                    return None
                for p in demux.feed(data):
                    on_data(p)
        finally:
            s.close()


def _msg(data: bytes) -> str:
    try:
        j = json.loads(data)
        if isinstance(j, dict) and j.get("message"):
            return str(j["message"])
    except ValueError:
        pass
    return data.decode("utf-8", "replace").strip()[:300]


class DockerRunner(Runner):
    name = "docker"

    def __init__(self, api: DockerAPI | None = None):
        self.api = api or DockerAPI()
        self.cid: str | None = None

    def setup(self, job, checkout, log):
        self.api.ensure_image(job.image, log)
        name = f"kern-ci-{job.labels.get('kern.ci.run', 'x')}-{uuid.uuid4().hex[:8]}"
        cfg = {
            "Image": job.image,
            "Entrypoint": ["sh", "-c", "while :; do sleep 1; done"],
            "Cmd": [],
            "WorkingDir": "/" + WORKDIR,
            "Labels": {LABEL: "1", **{k: str(v) for k, v in job.labels.items()}},
            "Env": ["CI=1"],
            "HostConfig": {},
        }
        mem = os.environ.get("KERN_CI_DOCKER_MEMORY_MB")
        if mem and mem.isdigit():
            cfg["HostConfig"]["Memory"] = int(mem) * 1024 * 1024
        if os.environ.get("KERN_CI_DOCKER_NETWORK"):
            cfg["HostConfig"]["NetworkMode"] = os.environ["KERN_CI_DOCKER_NETWORK"]
        self.cid = self.api.json("POST", f"/containers/create?name={name}", cfg)["Id"]
        self.api.call("POST", f"/containers/{self.cid}/start")
        size = checkout.stat().st_size
        with open(checkout, "rb") as f:
            self.api.call("PUT", f"/containers/{self.cid}/archive?path=/", body=f,
                          headers={"Content-Type": "application/x-tar", "Content-Length": str(size)}, timeout=300)

    def exec(self, job, step, env, timeout, log, cancelled):
        full = dict(env)
        create = {
            "AttachStdout": True, "AttachStderr": True, "Tty": False,
            "WorkingDir": "/" + WORKDIR,
            "Env": [f"{k}={v}" for k, v in full.items()],
            "Cmd": ["sh", "-c", 'exec "$(command -v bash || command -v sh)" -e -c "$0"', step.script],
        }
        eid = self.api.json("POST", f"/containers/{self.cid}/exec", create)["Id"]
        reason = self.api.exec_stream(eid, log.write, timeout, cancelled)
        if reason:
            try:  # the step is stuck or unwanted: the job ends here, so stop the whole container
                self.api.call("POST", f"/containers/{self.cid}/kill", timeout=15)
            except DockerError:
                pass
            return ExecResult(None, reason)
        code = None
        for _ in range(50):
            info = self.api.json("GET", f"/exec/{eid}/json")
            if not info.get("Running"):
                code = info.get("ExitCode")
                break
            time.sleep(0.1)
        return ExecResult(code if code is not None else 1)

    def collect(self, job, sink):
        conn = _UnixConnection(self.api.sock, 600)
        try:
            conn.request("GET", f"/containers/{self.cid}/archive?path=/{WORKDIR}")
            r = conn.getresponse()
            if r.status != 200:
                raise DockerError(f"Could not copy artifacts out: {_msg(r.read())}")
            with tarfile.open(fileobj=r, mode="r|") as tf:
                for m in tf:
                    if not m.isreg():
                        continue
                    rel = m.name.split("/", 1)[1] if "/" in m.name else ""
                    if rel and m.name.startswith(WORKDIR + "/") and sink.wants(rel):
                        sink.add(rel, tf.extractfile(m))
        except (OSError, http.client.HTTPException, tarfile.TarError) as e:
            raise DockerError(f"Could not copy artifacts out: {e}")
        finally:
            conn.close()

    def teardown(self):
        if self.cid:
            cid, self.cid = self.cid, None
            try:
                self.api.call("DELETE", f"/containers/{cid}?force=true&v=true", timeout=30, ok=(200, 204, 404))
            except DockerError:
                pass

    def cleanup_stale(self) -> int:
        """Remove containers left behind by a crashed worker (all carry the kern.ci label)."""
        flt = quote(json.dumps({"label": [f"{LABEL}=1"]}))
        n = 0
        for c in self.api.json("GET", f"/containers/json?all=1&filters={flt}") or []:
            try:
                self.api.call("DELETE", f"/containers/{c['Id']}?force=true&v=true", timeout=30, ok=(200, 204, 404))
                n += 1
            except DockerError:
                pass
        return n


def get_runner() -> Runner:
    kind = os.environ.get("KERN_CI_RUNNER", "docker").strip().lower()
    if kind == "shell":
        return ShellRunner()
    if kind == "docker":
        return DockerRunner()
    raise RunnerError(f"Unknown KERN_CI_RUNNER {kind!r} (use docker or shell).")
