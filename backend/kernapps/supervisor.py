"""The supervisor: keeps every enabled app running, runs deployments, and knows where each app listens.

One asyncio loop in the worker process (``manage.py apps_worker``). Database work happens in threads
(:func:`db`) because Django's ORM is synchronous. State changes are written to the shared database
only when they change; live numbers (CPU, memory, uptime) stay in memory and the backend asks for
them over the control port.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from django.db import close_old_connections, connections
from django.utils import timezone

from . import core, deploy, isolation
from .models import App, Deployment

log = logging.getLogger("kern.apps")

START_TIMEOUT = int(os.environ.get("KERN_APPS_START_TIMEOUT", 60))
STOP_GRACE = 10
LOG_MAX = 4 * 1024 * 1024
CRASH_WINDOW = 300  # seconds
CRASH_LIMIT = 5  # crashes inside the window before Kern stops trying
HEALTHY_AFTER = 60  # a run this long resets the backoff
PORTS = range(9200, 9999)
TAIL_LINES = 40  # the app's newest lines kept for the deploy log when it fails to start
CMD_MAX = 200  # characters of a command line shown in the task list
CONCURRENT_DEPLOYS = int(os.environ.get("KERN_APPS_CONCURRENT_DEPLOYS", 2))


async def db(fn, *args, **kw):
    """Run ORM code in a thread, with fresh connections."""
    def run():
        close_old_connections()
        try:
            return fn(*args, **kw)
        finally:
            connections.close_all()

    return await asyncio.to_thread(run)


# --------------------------------------------------------------------------- logs


class AppLog:
    """The app's output, one timestamped line at a time, rotated at LOG_MAX (one old file kept)."""

    def __init__(self, app_id: int):
        self.path = core.app_log(app_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, text: str, stream: str = "out"):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mark = {"out": " ", "err": "!", "kern": "#"}[stream]
        try:
            if self.path.exists() and self.path.stat().st_size > LOG_MAX:
                os.replace(self.path, self.path.with_suffix(".log.1"))
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                for line in text.rstrip("\n").split("\n"):
                    f.write(f"{ts} {mark} {line}\n")
        except OSError:
            log.exception("cannot write the log of app %s", self.path)

    def kern(self, text: str):
        self.write(text, "kern")


# ----------------------------------------------------------------------- runtime


@dataclass
class Instance:
    """One running release of an app (a process, or just a folder for a static app)."""

    app_id: int
    number: int
    plan: core.Plan
    release: Path
    port: int = 0
    proc: asyncio.subprocess.Process | None = None
    started: float = field(default_factory=time.time)
    stopping: bool = False
    static_root: Path | None = None
    tasks: list = field(default_factory=list)
    cpu: float = 0.0
    rss: int = 0
    _cpu_last: tuple[float, float] | None = None
    tail: deque = field(default_factory=lambda: deque(maxlen=TAIL_LINES))  # what it printed last: (stream, line)
    ready_note: str = ""  # how the start check ended, for the deploy log

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def alive(self) -> bool:
        return self.static_root is not None or (self.proc is not None and self.proc.returncode is None)


@dataclass
class Runtime:
    """What the supervisor knows about one app."""

    app: dict  # a snapshot of the row (see snapshot())
    current: Instance | None = None
    deploying: int | None = None  # deployment number being built or started
    crashes: list = field(default_factory=list)
    backoff_until: float = 0.0
    held: bool = False  # crashed too often; waits for a restart from the UI
    restarts: int = 0
    last_exit: int | None = None
    starting: bool = False


def snapshot(a: App) -> dict:
    return {
        "id": a.id, "owner": a.owner, "slug": a.slug, "name": a.name, "icon": a.icon, "access": a.access,
        "public_paths": list(a.public_paths or []), "strip_prefix": a.strip_prefix, "enabled": a.enabled,
        "secret": a.secret, "hook_secret": a.hook_secret, "live": a.live.number if a.live_id and a.live else None,
        # A rollback reuses the files (release folder) of the deployment it went back to.
        "release": (a.live.rollback_of or a.live.number) if a.live_id and a.live else None,
        "state": a.state,
    }


class _Row:
    """Enough of an App row for core.app_env (which wants attributes)."""

    def __init__(self, a: App):
        self.__dict__.update({k: getattr(a, k) for k in ("id", "slug", "name", "secret", "env_enc")})


def free_port() -> int:
    ports = list(PORTS)
    random.shuffle(ports)
    for p in ports:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("No free port for the app.")


def _proc_stats(pgid: int) -> tuple[int, float]:
    """(rss bytes, cpu seconds) of every process in the group."""
    rss, cpu = 0, 0.0
    tick = os.sysconf("SC_CLK_TCK")
    page = os.sysconf("SC_PAGE_SIZE")
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        rest = stat.rsplit(")", 1)[-1].split()
        try:
            if int(rest[2]) != pgid:  # field 5: pgrp
                continue
            cpu += (int(rest[11]) + int(rest[12])) / tick  # utime + stime
            rss += int(rest[21]) * page
        except (IndexError, ValueError):
            continue
    return rss, cpu


def _scan_proc() -> dict[int, dict]:
    """pid → {ppid, pgrp, cpu (seconds), start (ticks after boot), rss (bytes), name, state} of every process.
    Reads only /proc/<pid>/stat."""
    out = {}
    page = os.sysconf("SC_PAGE_SIZE")
    tick = os.sysconf("SC_CLK_TCK")
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        lp, rp = stat.find("("), stat.rfind(")")
        rest = stat[rp + 1:].split()
        try:
            out[int(d)] = {"name": stat[lp + 1:rp], "state": rest[0], "ppid": int(rest[1]), "pgrp": int(rest[2]),
                           "cpu": (int(rest[11]) + int(rest[12])) / tick, "start": int(rest[19]) / tick,
                           "rss": int(rest[21]) * page}
        except (IndexError, ValueError):
            continue
    return out


def _cmdline(pid: int, name: str, state: str) -> str:
    """The command line, cut at CMD_MAX characters. Never the environment."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read(4 * CMD_MAX)
    except OSError:
        raw = b""
    cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
    if not cmd:
        cmd = f"[{name}]"
    if state == "Z":
        cmd += " <defunct>"
    return cmd[:CMD_MAX]


class Supervisor:
    def __init__(self):
        self.apps: dict[int, Runtime] = {}
        self.by_slug: dict[str, int] = {}
        self.wake = asyncio.Event()
        self.stopping = False
        self.deploy_sem = asyncio.Semaphore(CONCURRENT_DEPLOYS)
        self.deploy_tasks: dict[int, asyncio.Task] = {}  # app id → task
        self.builder = None  # set by the worker (AI builder runner)
        self._cpu_prev: dict[int, tuple[float, float, float]] = {}  # pid → (when, cpu seconds, start) of the last look
        self._cpu_lock = threading.Lock()

    # ------------------------------------------------------------------ lookups

    def find(self, slug: str) -> Runtime | None:
        i = self.by_slug.get(slug)
        return self.apps.get(i) if i is not None else None

    def status(self) -> dict:
        out = {}
        now = time.time()
        for i, rt in list(self.apps.items()):  # a copy: the builder's thread asks too
            c = rt.current
            out[str(i)] = {
                "running": bool(c and c.alive()), "pid": c.pid if c else None, "port": c.port if c else None,
                "number": c.number if c else None, "uptime": int(now - c.started) if c and c.alive() else 0,
                "cpu": round(c.cpu, 1) if c else 0, "rss": c.rss if c else 0, "restarts": rt.restarts,
                "held": rt.held, "deploying": rt.deploying, "last_exit": rt.last_exit,
                "backoff": max(0, int(rt.backoff_until - now)) if rt.backoff_until > now else 0,
            }
        return {"isolated": isolation.isolated(), "apps": out}

    def processes(self, app_id: int) -> list[dict]:
        """The processes of the app's running release: its process group and everything started under it.

        ``cpu`` is a percentage of one core since the last time this was asked (the average over the
        process's life the first time). ``mem_bytes`` is resident memory. Safe to call from any thread."""
        rt = self.apps.get(app_id)
        inst = rt.current if rt else None
        if inst is None or inst.proc is None or inst.proc.returncode is not None:
            return []
        root = inst.proc.pid
        table = _scan_proc()
        kids: dict[int, list[int]] = {}
        for pid, p in table.items():
            kids.setdefault(p["ppid"], []).append(pid)
        members, todo = set(), [root]
        while todo:  # descendants (they may have left the group)
            pid = todo.pop()
            if pid in members or pid not in table:
                continue
            members.add(pid)
            todo.extend(kids.get(pid, []))
        members |= {pid for pid, p in table.items() if p["pgrp"] == root}
        try:
            with open("/proc/uptime") as f:
                uptime = float(f.read().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = time.time() - inst.started
        now, out = time.monotonic(), []
        with self._cpu_lock:
            for pid in sorted(members, key=lambda x: (x != root, x)):
                p = table[pid]
                age = max(0.0, uptime - p["start"])
                prev = self._cpu_prev.get(pid)
                if prev and prev[2] == p["start"] and now - prev[0] >= 0.5:
                    pct = 100 * max(0.0, p["cpu"] - prev[1]) / (now - prev[0])
                else:
                    pct = 100 * p["cpu"] / age if age > 0.5 else 0.0
                if not prev or now - prev[0] >= 0.5:
                    self._cpu_prev[pid] = (now, p["cpu"], p["start"])
                out.append({"pid": pid, "ppid": p["ppid"], "cmd": _cmdline(pid, p["name"], p["state"]), "cpu": round(pct, 1),
                            "mem_bytes": p["rss"], "age_s": int(age)})
            for pid in set(self._cpu_prev) - set(table):
                self._cpu_prev.pop(pid, None)
        return out

    # -------------------------------------------------------------------- state

    async def set_state(self, rt: Runtime, state: str, detail: str = ""):
        if rt.app.get("state") == state and rt.app.get("detail", "") == detail:
            return
        rt.app["state"], rt.app["detail"] = state, detail
        await db(lambda: App.objects.filter(pk=rt.app["id"]).update(state=state, state_detail=detail[:500], state_at=timezone.now()))

    # --------------------------------------------------------------------- sync

    async def sync(self):
        rows = await db(lambda: [snapshot(a) for a in App.objects.select_related("live").all()])
        seen = set()
        for snap in rows:
            seen.add(snap["id"])
            rt = self.apps.get(snap["id"])
            if rt is None:
                rt = self.apps[snap["id"]] = Runtime(app=snap)
            else:
                snap["detail"] = rt.app.get("detail", "")
                snap["state"] = rt.app.get("state", snap["state"])
                rt.app = snap
        for gone in set(self.apps) - seen:
            rt = self.apps.pop(gone)
            if gone in self.deploy_tasks:
                self.deploy_tasks.pop(gone).cancel()
            if rt.current:
                await self.stop_instance(rt.current)
            await asyncio.to_thread(isolation.remove_app, gone)
        self.by_slug = {rt.app["slug"]: i for i, rt in self.apps.items()}
        now = time.time()
        for rt in list(self.apps.values()):
            a = rt.app
            want = a["enabled"] and a["live"] is not None
            if want and rt.current is None and rt.deploying is None and not rt.held and not rt.starting and now >= rt.backoff_until:
                asyncio.create_task(self.start_live(rt))
            elif not want and rt.current is not None and rt.deploying is None:
                inst, rt.current = rt.current, None
                await self.stop_instance(inst)
                AppLog(a["id"]).kern("Stopped.")
            if not want and rt.current is None and rt.deploying is None and a["live"] is not None:
                await self.set_state(rt, "stopped")
        await self.pick_deployments()

    async def pick_deployments(self):
        queued = await db(lambda: list(Deployment.objects.filter(status="queued").order_by("created").values_list("pk", "app_id")))
        for pk, app_id in queued:
            rt = self.apps.get(app_id)
            if rt is None or app_id in self.deploy_tasks:
                continue
            self.deploy_tasks[app_id] = asyncio.create_task(self.run_deployment(rt, pk))

    # ------------------------------------------------------------------ deploys

    async def run_deployment(self, rt: Runtime, pk: int):
        app_id = rt.app["id"]
        try:
            async with self.deploy_sem:
                dep = await db(lambda: Deployment.objects.select_related("app").filter(pk=pk, status="queued").first())
                if dep is None:
                    return
                rt.deploying = dep.number
                if rt.current is None:
                    await self.set_state(rt, "building", f"Deployment #{dep.number}")
                cancel_flag = {"v": False}

                def cancelled():
                    if not cancel_flag["v"]:
                        cancel_flag["v"] = Deployment.objects.filter(pk=pk, status="cancelled").exists()
                    return cancel_flag["v"]

                try:
                    plan, release = await db(deploy.build, dep, cancelled)
                except deploy.DeployError as e:
                    await db(deploy.finish, dep, False, str(e))
                    if rt.current is None:
                        await self.set_state(rt, "failed", f"Deployment #{dep.number} failed: {e}")
                    return
                enabled = await db(lambda: App.objects.filter(pk=app_id).values_list("enabled", flat=True).first())
                if not enabled:
                    # Built while stopped: it becomes the live release and starts with the app.
                    await db(deploy.finish, dep, True, "", "built while the app is stopped; it starts when you start the app")
                    await self.set_state(rt, "stopped")
                    return
                dl = deploy.Log(core.deploy_log(app_id, dep.number))
                try:
                    inst, err = await self.launch(rt, dep.number, plan, release, dl)
                    if inst is None:
                        await db(deploy.finish, dep, False, err)
                        if rt.current is None:
                            await self.set_state(rt, "failed", f"Deployment #{dep.number} failed: {err}")
                        return
                    dl.phase("Switch traffic")
                    old, rt.current = rt.current, inst
                    rt.held, rt.crashes, rt.backoff_until = False, [], 0
                    dl.end(True, f"#{dep.number} serves /{rt.app['slug']}/" + (f" on port {inst.port}" if inst.port else "")
                           + (f" (was #{old.number})" if old else ""))
                    if old:
                        # Before the deployment is marked live: the UI stops reading the log once it is over.
                        dl.phase(f"Stop the old version #{old.number}")
                        await self.stop_instance(old)
                        dl.end(True, f"#{old.number} stopped")
                finally:
                    dl.close()
                await db(deploy.finish, dep, True)
                rt.app["live"], rt.app["release"] = dep.number, dep.rollback_of or dep.number
                await self.set_state(rt, "running")
                AppLog(app_id).kern(f"Deployment #{dep.number} is live" + (f" on port {inst.port}." if inst.port else "."))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("deployment %s crashed", pk)
        finally:
            rt.deploying = None
            self.deploy_tasks.pop(app_id, None)
            self.wake.set()

    # ------------------------------------------------------------------ processes

    async def start_live(self, rt: Runtime):
        """Start the live release (after a server restart, a crash or the start button)."""
        a = rt.app
        rt.starting = True
        try:
            number = a["live"]
            plan = deploy.load_plan(a["id"], number)
            release = core.release_dir(a["id"], a.get("release") or number)
            if plan is None or not release.is_dir():
                await self.set_state(rt, "failed", "The files of the live deployment are missing. Deploy again.")
                rt.held = True
                return
            await self.set_state(rt, "starting")
            inst, err = await self.launch(rt, number, plan, release)
            if inst is None:
                self.note_crash(rt, None)
                await self.set_state(rt, "crashed", err if rt.held else f"{err} Trying again in {int(rt.backoff_until - time.time())} s.")
                asyncio.get_running_loop().call_later(max(0.1, rt.backoff_until - time.time() + 0.1), self.wake.set)
                return
            rt.current = inst
            await self.set_state(rt, "running")
        finally:
            rt.starting = False

    async def launch(self, rt: Runtime, number: int, plan: core.Plan, release: Path, dlog=None) -> tuple[Instance | None, str]:
        """Start a release and wait until it answers. ``dlog``: the deploy log to write the phases to (a
        deployment); None when the live release is started again after a crash or a restart."""
        a = rt.app
        lg = AppLog(a["id"])
        dl = dlog or deploy.NullLog()
        if plan.runtime == "static":
            dl.phase("Start", "static files, no process")
            root = core.static_root(release, plan)
            if not (root / "index.html").is_file() and not root.is_dir():
                dl.end(False, "the static files are missing")
                return None, "The static files are missing."
            dl.end(True, "served by Kern")
            return Instance(a["id"], number, plan, release, static_root=root), ""
        row = await db(lambda: App.objects.filter(pk=a["id"]).first())
        if row is None:
            dl.end(False, "the app was deleted")
            return None, "The app was deleted."
        port = free_port()
        env = core.app_env(_Row(row), port, release, plan, core.home_dir(a["id"]))
        cmd = isolation.wrap(["sh", "-c", plan.start], a["id"])
        dl.phase(f"Start on port {port}", plan.start)
        lg.kern(f"Starting deployment #{number}: {plan.start}")
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(release), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                        start_new_session=True)
        except OSError as e:
            lg.kern(f"Could not start: {e}")
            dl.end(False, f"could not start: {e}")
            return None, f"Could not start: {e}"
        inst = Instance(a["id"], number, plan, release, port=port, proc=proc)
        inst.tasks = [asyncio.create_task(self._pump(proc.stdout, lg, "out", inst)),
                      asyncio.create_task(self._pump(proc.stderr, lg, "err", inst))]
        dl.end(True, f"process {proc.pid} started")
        dl.phase("Wait for the app to answer", f"port {port}" + (f", GET {plan.health}" if plan.health else "")
                 + f", up to {START_TIMEOUT} s")
        ok, err = await self.wait_ready(inst, lg)
        if not ok:
            await self.stop_instance(inst)
            await asyncio.wait(inst.tasks, timeout=2)  # let the last of its output arrive
            dl.end(False, err)
            self._dump_tail(dl, inst)
            return None, err
        dl.end(True, inst.ready_note or "answered")
        inst.tasks.append(asyncio.create_task(self._watch(rt, inst)))
        return inst, ""

    @staticmethod
    def _dump_tail(dl, inst: Instance):
        """What the app printed last, into the deploy log: the reason it did not start is usually there."""
        lines = list(inst.tail)
        if not lines:
            dl.line("The app printed nothing.")
            return
        dl.line(f"The app's last {len(lines)} line{'s' if len(lines) != 1 else ''} of output (! = stderr):")
        for kind, text in lines:
            dl.line(f"  {'!' if kind == 'err' else '|'} {text}")

    async def _pump(self, stream, lg: AppLog, kind: str, inst: Instance | None = None):
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace")
            lg.write(text, kind)
            if inst is not None:
                for part in text.rstrip("\n").split("\n"):
                    inst.tail.append((kind, part[:500]))

    async def wait_ready(self, inst: Instance, lg: AppLog) -> tuple[bool, str]:
        deadline = time.monotonic() + START_TIMEOUT
        port_open, last_status = False, None
        while time.monotonic() < deadline:
            if inst.proc.returncode is not None:
                return False, f"The app exited with code {inst.proc.returncode} while starting. See the app log."
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", inst.port), 1)
                w.close()
                port_open = True
                if not inst.plan.health:
                    inst.ready_note = f"port {inst.port} open"
                    return True, ""
                status = await self._http_status(inst.port, inst.plan.health)
                last_status = status or last_status
                if status and status < 500:
                    inst.ready_note = f"GET {inst.plan.health} answered {status}"
                    return True, ""
            except (OSError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.3)
        msg = (f"The app did not answer on port $PORT ({inst.port}) within {START_TIMEOUT} s. "
               "It has to listen on the port in the PORT environment variable.")
        if inst.plan.health:
            msg = f"{inst.plan.health} did not answer with a success within {START_TIMEOUT} s."
            if last_status:
                msg += f" (The last answer was {last_status}.)"
            elif port_open:
                msg += " (The port was open, but the path gave no HTTP answer.)"
        lg.kern(msg)
        return False, msg

    async def _http_status(self, port: int, path: str) -> int | None:
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 2)
            w.write(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
            await w.drain()
            line = await asyncio.wait_for(r.readline(), 3)
            w.close()
            return int(line.split()[1])
        except (OSError, asyncio.TimeoutError, ValueError, IndexError):
            return None

    async def _watch(self, rt: Runtime, inst: Instance):
        code = await inst.proc.wait()
        for t in inst.tasks[:2]:
            try:
                await asyncio.wait_for(t, 2)
            except (asyncio.TimeoutError, Exception):
                pass
        if inst.stopping or self.stopping:
            return
        lg = AppLog(rt.app["id"])
        lg.kern(f"The app exited with code {code}.")
        rt.last_exit = code
        if rt.current is inst:
            rt.current = None
            self.note_crash(rt, inst)
            if rt.held:
                await self.set_state(rt, "crashed", f"Exited with code {code}, {CRASH_LIMIT} times in a few minutes. "
                                                    "Kern stopped restarting it: fix the problem and restart.")
                lg.kern("Crashed too often; not restarting until you restart it.")
            else:
                wait = int(rt.backoff_until - time.time())
                await self.set_state(rt, "crashed", f"Exited with code {code}. Restarting in {wait} s.")
                lg.kern(f"Restarting in {wait} s.")
                asyncio.get_running_loop().call_later(wait + 0.1, self.wake.set)

    def note_crash(self, rt: Runtime, inst: Instance | None):
        now = time.time()
        if inst and now - inst.started > HEALTHY_AFTER:
            rt.crashes = []
        rt.crashes = [t for t in rt.crashes if now - t < CRASH_WINDOW] + [now]
        rt.restarts += 1
        if len(rt.crashes) >= CRASH_LIMIT:
            rt.held = True
        rt.backoff_until = now + min(60, 2 ** (len(rt.crashes) - 1))

    async def stop_instance(self, inst: Instance):
        inst.stopping = True
        p = inst.proc
        if p is None or p.returncode is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            log.error("not allowed to stop app %s (pid %s): the worker needs CAP_KILL", inst.app_id, p.pid)
            return
        try:
            await asyncio.wait_for(p.wait(), STOP_GRACE)
        except asyncio.TimeoutError:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await p.wait()

    async def restart(self, app_id: int):
        rt = self.apps.get(app_id)
        if rt is None:
            return
        rt.held, rt.crashes, rt.backoff_until = False, [], 0
        if rt.current:
            inst, rt.current = rt.current, None
            await self.stop_instance(inst)
            AppLog(app_id).kern("Restarting.")
        self.wake.set()

    # --------------------------------------------------------------------- loops

    async def metrics_loop(self):
        while not self.stopping:
            for rt in list(self.apps.values()):
                inst = rt.current
                if not inst or not inst.proc or inst.proc.returncode is not None:
                    continue
                rss, cpu = await asyncio.to_thread(_proc_stats, inst.proc.pid)
                now = time.monotonic()
                if inst._cpu_last:
                    t0, c0 = inst._cpu_last
                    inst.cpu = max(0.0, 100 * (cpu - c0) / max(0.001, now - t0))
                inst._cpu_last = (now, cpu)
                inst.rss = rss
            await asyncio.sleep(5)

    async def run(self):
        await db(deploy.recover)
        await asyncio.to_thread(isolation.harden_data_dir)
        asyncio.create_task(self.metrics_loop())
        last_harden = time.monotonic()
        while not self.stopping:
            try:
                await self.sync()
            except Exception:
                log.exception("sync failed")
            if self.builder:
                try:
                    await self.builder.poll()
                except Exception:
                    log.exception("builder poll failed")
            if time.monotonic() - last_harden > 300:
                await asyncio.to_thread(isolation.harden_data_dir)
                last_harden = time.monotonic()
            try:
                await asyncio.wait_for(self.wake.wait(), 3)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    async def shutdown(self):
        self.stopping = True
        for t in self.deploy_tasks.values():
            t.cancel()
        await asyncio.gather(*(self.stop_instance(rt.current) for rt in self.apps.values() if rt.current),
                             return_exceptions=True)
