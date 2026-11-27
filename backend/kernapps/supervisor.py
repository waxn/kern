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
import time
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


class Supervisor:
    def __init__(self):
        self.apps: dict[int, Runtime] = {}
        self.by_slug: dict[str, int] = {}
        self.wake = asyncio.Event()
        self.stopping = False
        self.deploy_sem = asyncio.Semaphore(CONCURRENT_DEPLOYS)
        self.deploy_tasks: dict[int, asyncio.Task] = {}  # app id → task
        self.builder = None  # set by the worker (AI builder runner)

    # ------------------------------------------------------------------ lookups

    def find(self, slug: str) -> Runtime | None:
        i = self.by_slug.get(slug)
        return self.apps.get(i) if i is not None else None

    def status(self) -> dict:
        out = {}
        now = time.time()
        for i, rt in self.apps.items():
            c = rt.current
            out[str(i)] = {
                "running": bool(c and c.alive()), "pid": c.pid if c else None, "port": c.port if c else None,
                "number": c.number if c else None, "uptime": int(now - c.started) if c and c.alive() else 0,
                "cpu": round(c.cpu, 1) if c else 0, "rss": c.rss if c else 0, "restarts": rt.restarts,
                "held": rt.held, "deploying": rt.deploying, "last_exit": rt.last_exit,
                "backoff": max(0, int(rt.backoff_until - now)) if rt.backoff_until > now else 0,
            }
        return {"isolated": isolation.isolated(), "apps": out}

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
                    await db(deploy.finish, dep, True)
                    await self.set_state(rt, "stopped")
                    return
                inst, err = await self.launch(rt, dep.number, plan, release)
                if inst is None:
                    await db(deploy.finish, dep, False, err)
                    if rt.current is None:
                        await self.set_state(rt, "failed", f"Deployment #{dep.number} failed: {err}")
                    return
                old, rt.current = rt.current, inst
                rt.held, rt.crashes, rt.backoff_until = False, [], 0
                await db(deploy.finish, dep, True)
                rt.app["live"], rt.app["release"] = dep.number, dep.rollback_of or dep.number
                await self.set_state(rt, "running")
                AppLog(app_id).kern(f"Deployment #{dep.number} is live" + (f" on port {inst.port}." if inst.port else "."))
                if old:
                    await self.stop_instance(old)
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

    async def launch(self, rt: Runtime, number: int, plan: core.Plan, release: Path) -> tuple[Instance | None, str]:
        a = rt.app
        lg = AppLog(a["id"])
        if plan.runtime == "static":
            root = core.static_root(release, plan)
            if not (root / "index.html").is_file() and not root.is_dir():
                return None, "The static files are missing."
            return Instance(a["id"], number, plan, release, static_root=root), ""
        row = await db(lambda: App.objects.filter(pk=a["id"]).first())
        if row is None:
            return None, "The app was deleted."
        port = free_port()
        env = core.app_env(_Row(row), port, release, plan, core.home_dir(a["id"]))
        cmd = isolation.wrap(["sh", "-c", plan.start], a["id"])
        lg.kern(f"Starting deployment #{number}: {plan.start}")
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(release), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                        start_new_session=True)
        except OSError as e:
            lg.kern(f"Could not start: {e}")
            return None, f"Could not start: {e}"
        inst = Instance(a["id"], number, plan, release, port=port, proc=proc)
        inst.tasks = [asyncio.create_task(self._pump(proc.stdout, lg, "out")),
                      asyncio.create_task(self._pump(proc.stderr, lg, "err"))]
        ok, err = await self.wait_ready(inst, lg)
        if not ok:
            await self.stop_instance(inst)
            return None, err
        inst.tasks.append(asyncio.create_task(self._watch(rt, inst)))
        return inst, ""

    async def _pump(self, stream, lg: AppLog, kind: str):
        while True:
            line = await stream.readline()
            if not line:
                return
            lg.write(line.decode("utf-8", errors="replace"), kind)

    async def wait_ready(self, inst: Instance, lg: AppLog) -> tuple[bool, str]:
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if inst.proc.returncode is not None:
                return False, f"The app exited with code {inst.proc.returncode} while starting. See the app log."
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", inst.port), 1)
                w.close()
                if not inst.plan.health:
                    return True, ""
                status = await self._http_status(inst.port, inst.plan.health)
                if status and status < 500:
                    return True, ""
            except (OSError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.3)
        msg = (f"The app did not answer on port $PORT ({inst.port}) within {START_TIMEOUT} s. "
               "It has to listen on the port in the PORT environment variable.")
        if inst.plan.health:
            msg = f"{inst.plan.health} did not answer with a success within {START_TIMEOUT} s."
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
