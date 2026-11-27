"""Deployments: queue a build of a commit, and (in the worker) turn it into a release folder that is
ready to start. Starting it, checking it answers and moving traffic over is the supervisor's part
(:mod:`kernapps.worker`)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone as dtz
from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from . import core, isolation, source
from .models import App, Deployment

log = logging.getLogger("kern.apps")

BUILD_TIMEOUT = int(os.environ.get("KERN_APPS_BUILD_TIMEOUT", 15 * 60))
KEEP_RELEASES = 3
KEEP_DEPLOYS = 40


class DeployError(Exception):
    pass


# ----------------------------------------------------------------------- queueing


def queue(app: App, trigger: str, who: str = "", sha: str = "", subject: str = "", rollback_of: int | None = None) -> Deployment:
    """Add a deployment, unless the same commit is already waiting or building."""
    with transaction.atomic():
        if not rollback_of:
            dup = app.deployments.filter(status__in=("queued", "building"))
            dup = dup.filter(sha=sha) if sha else dup.filter(sha="", rollback_of__isnull=True)
            existing = dup.first()
            if existing:
                return existing
        n = (app.deployments.aggregate(m=Max("number"))["m"] or 0) + 1
        dep = Deployment.objects.create(app=app, number=n, sha=sha, subject=subject[:300], trigger=trigger,
                                        who=who[:150], ref=app.branch, rollback_of=rollback_of)
    kick()
    return dep


def kick() -> None:
    """Tell the worker to look now (it also looks every few seconds on its own)."""
    def go():
        try:
            import requests

            requests.post(core.control_url() + "/kick", headers={"X-Kern-Control": core.control_token()}, timeout=2)
        except Exception:
            pass

    threading.Thread(target=go, daemon=True).start()


# -------------------------------------------------------------------------- logs


def stamp(t: float | None = None) -> str:
    """``[HH:MM:SS]`` (UTC, like the app log) for the lines Kern writes itself."""
    return time.strftime("[%H:%M:%S]", time.gmtime(t))


def fmt_seconds(s: float) -> str:
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{round(s)} s"
    return f"{int(s // 60)} m {int(s % 60):02d} s"


def phases_path(app_id: int, number: int) -> Path:
    return core.logs_dir(app_id) / f"deploy-{int(number)}.phases.json"


class Log:
    """The deploy log: plain text lines, the newest deployment's is what the UI streams.

    Lines Kern writes itself start with ``[HH:MM:SS]`` (UTC) and a marker the UI styles (``▸`` a phase
    begins, ``✓`` / ``✗`` a phase ended or the deployment did); ``$ cmd`` is a command; what builds and
    apps print is written as it comes, without a time. Every phase is also recorded in ``deploy-<n>.phases.json``
    (``[{name, status: running|ok|fail, started, seconds, detail}]``), which the deploy_log API hands out as
    ``phases``. Several ``Log`` objects write one deployment's log one after the other (build, start, finish):
    each picks up the phases of the one before.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8", errors="replace")
        self.ppath = path.with_suffix(".phases.json")
        try:
            data = json.loads(self.ppath.read_text())
            self.phases = [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []
        except (OSError, ValueError):
            self.phases = []

    # -- text
    def line(self, text: str):
        self.fh.write(text.rstrip("\n") + "\n")
        self.fh.flush()

    def info(self, text: str):
        """A plain line with the time in front."""
        self.line(f"{stamp()} {text}")

    # -- phases
    def _save(self):
        try:
            tmp = self.ppath.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.phases))
            os.replace(tmp, self.ppath)
        except OSError:
            log.warning("cannot write %s", self.ppath)

    @property
    def running(self) -> dict | None:
        return self.phases[-1] if self.phases and self.phases[-1].get("status") == "running" else None

    def phase(self, name: str, detail: str = ""):
        """End the running phase (as done) and begin another: ``[12:00:01] ▸ name — detail``."""
        self.end()
        now = time.time()
        self.phases.append({"name": name, "status": "running", "t": now, "started": _iso(now), "seconds": None, "detail": detail})
        self.line(f"\n{stamp(now)} ▸ {name}" + (f" — {detail}" if detail else ""))
        self._save()

    def end(self, ok: bool = True, note: str = ""):
        """End the running phase: ``[12:00:03] ✓ note · 1.2 s`` (or ``✗`` when it failed)."""
        p = self.running
        if p is None:
            return
        now = time.time()
        p["seconds"] = round(max(0.0, now - p["t"]), 2)
        p["status"] = "ok" if ok else "fail"
        if note:
            p["detail"] = note if not p.get("detail") else p["detail"]
        self.line(f"{stamp(now)} {'✓' if ok else '✗'} {note or ('done' if ok else 'failed')} · {fmt_seconds(p['seconds'])}")
        self._save()

    def step(self, text: str):  # kept for callers that only want a header
        self.phase(text)

    def close(self):
        self.fh.close()


class NullLog:
    """Stands in for a Log where there is no deployment (restarting the live release after a crash)."""

    running = None

    def __getattr__(self, name):
        return lambda *a, **kw: None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, dtz.utc).isoformat()


def read_phases(app_id: int, number: int, finished: bool = False) -> list[dict]:
    """The phases of a deployment for the API. A phase still ``running`` in a finished deployment (the worker
    died) is shown as failed; a running one gets its seconds so far."""
    try:
        data = json.loads(phases_path(app_id, number).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for p in data if isinstance(data, list) else []:
        if not isinstance(p, dict) or "name" not in p:
            continue
        status, secs = p.get("status", "ok"), p.get("seconds")
        if status == "running":
            secs = round(max(0.0, time.time() - float(p.get("t") or time.time())), 1)
            if finished:
                status = "fail"
        out.append({"name": p["name"], "status": status, "started": p.get("started"), "seconds": secs, "detail": p.get("detail", "")})
    return out


def tail(path: Path, max_bytes: int = 4000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def plan_path(app_id: int, number: int) -> Path:
    return core.logs_dir(app_id) / f"plan-{int(number)}.json"


def load_plan(app_id: int, number: int) -> core.Plan | None:
    try:
        return core.Plan.from_json(json.loads(plan_path(app_id, number).read_text()))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------- build


def _mark(dep: Deployment, status: str, **kw):
    kw["status"] = status
    Deployment.objects.filter(pk=dep.pk).update(**kw)
    for k, v in kw.items():
        setattr(dep, k, v)


def _run_step(app: App, cmd: str, cwd: Path, env: dict, lg: Log, cancelled, label: str = "") -> None:
    """One build command: its own phase, its output merged (stdout and stderr), then exit code and duration."""
    lg.phase(f"Build{label}: {cmd if len(cmd) <= 70 else cmd[:67] + '…'}")
    lg.line(f"$ {cmd}")
    p = subprocess.Popen(isolation.wrap(["sh", "-c", cmd], app.id), cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    start = time.monotonic()
    assert p.stdout
    for raw in p.stdout:
        lg.line(raw.decode("utf-8", errors="replace").rstrip("\n"))
        if time.monotonic() - start > BUILD_TIMEOUT or cancelled():
            break
    try:
        p.wait(timeout=max(1, BUILD_TIMEOUT - (time.monotonic() - start)))
    except subprocess.TimeoutExpired:
        pass
    if p.poll() is None:
        try:
            os.killpg(p.pid, 9)
        except OSError:
            pass
        p.wait()
        if cancelled():
            lg.end(False, "cancelled")
            raise DeployError("Cancelled.")
        lg.end(False, "timed out")
        raise DeployError(f"“{cmd}” took longer than {BUILD_TIMEOUT // 60} minutes.")
    if p.returncode:
        code = f"killed by signal {-p.returncode}" if p.returncode < 0 else f"exit {p.returncode}"
        lg.end(False, code)
        raise DeployError(f"“{cmd}” failed (exit code {p.returncode}). See the build log.")
    lg.end(True, "exit 0")


def build(dep: Deployment, cancelled=lambda: False) -> tuple[core.Plan, Path]:
    """Prepare the release folder of ``dep``. Returns (plan, release). Raises DeployError."""
    app = dep.app
    lg = Log(core.deploy_log(app.id, dep.number))
    _mark(dep, "building", started=timezone.now())
    try:
        lg.line(f"{stamp()} Deployment #{dep.number} of {app.name} (/{app.slug}/) · {dep.trigger}" + (f" by {dep.who}" if dep.who else ""))
        try:
            isolation.prepare(app.id)
        except isolation.IsolationError as e:
            raise DeployError(str(e))
        if dep.rollback_of:
            lg.phase(f"Roll back to deployment #{dep.rollback_of}", dep.sha[:10])
            release = core.release_dir(app.id, dep.rollback_of)
            plan = load_plan(app.id, dep.rollback_of)
            if not release.is_dir() or plan is None:
                raise DeployError(f"The files of deployment #{dep.rollback_of} are gone (only the newest "
                                  f"{KEEP_RELEASES} are kept). Deploy that commit again instead.")
            lg.line(f"Reusing the files of #{dep.rollback_of}; runtime: {plan.runtime}" + (f" · start: {plan.start}" if plan.start else ""))
            plan_path(app.id, dep.number).write_text(json.dumps(plan.as_json()))
            _mark(dep, "starting", runtime=plan.runtime)
            lg.end(True, "files and plan found")
            return plan, release

        lg.phase("Get the code", f"branch {app.branch}")
        try:
            gd = source.git_dir(app)
            if app.source == "url":
                lg.line(f"Fetched {app.git_url} ({app.branch})")
            sha, subject = source.resolve(app, gd, dep.sha or None)
        except source.SourceError as e:
            raise DeployError(str(e))
        _mark(dep, "building", sha=sha, subject=dep.subject or subject)
        lg.line(f"Commit {sha[:10]} · {dep.subject or subject}")
        lg.end(True, f"commit {sha[:10]}")

        lg.phase("Write the release", f"releases/{dep.number}")
        release = core.release_dir(app.id, dep.number)
        isolation.remove_tree(app.id, release)
        try:
            source.export(app, gd, sha, release)
        except source.SourceError as e:
            raise DeployError(str(e))
        lg.end(True, "files written")

        lg.phase("Plan")
        try:
            plan = core.make_plan(app, release)
        except core.PlanError as e:
            raise DeployError(str(e))
        for n in plan.notes:
            lg.line(n)
        lg.line(f"Runtime: {plan.runtime}" + (f" · start: {plan.start}" if plan.start else ""))
        home = core.home_dir(app.id)

        steps = list(plan.build)
        if plan.runtime == "python" and (release / "requirements.txt").is_file() and not app.build_cmd:
            steps.insert(0, "python3 -m venv .venv")
        lg.end(True, f"{plan.runtime}, {len(steps)} build step{'s' if len(steps) != 1 else ''}")
        for i, cmd in enumerate(steps, 1):
            # The environment is made again for each step, so a fresh .venv or node_modules is on PATH.
            env = core.build_env(app, release, home)
            _run_step(app, cmd, release, env, lg, cancelled, f" {i}/{len(steps)}" if len(steps) > 1 else "")
        if plan.runtime == "static":
            lg.phase("Check the static files")
            root = core.static_root(release, plan)
            if not (root / "index.html").is_file():
                raise DeployError(f"There is no index.html to serve (looked in {root.relative_to(release) or 'the app folder'}).")
            lg.end(True, "index.html found")
        plan_path(app.id, dep.number).write_text(json.dumps(plan.as_json()))
        _mark(dep, "starting", runtime=plan.runtime)
        return plan, release
    except DeployError as e:
        lg.end(False, "failed")  # the reason is written by finish()
        raise
    except Exception as e:  # a bug of ours: still end the deployment cleanly
        log.exception("deploy %s failed", dep.pk)
        lg.end(False, "failed")
        raise DeployError(f"Kern hit an error while deploying: {e}")
    finally:
        lg.close()


def finish(dep: Deployment, ok: bool, error: str = "", note: str = "") -> None:
    """Record the outcome. On success this deployment becomes the app's live one.

    The last lines of the log are written *before* the status changes: the UI stops reading once the
    status says it is over and it has caught up with the file."""
    lg = Log(core.deploy_log(dep.app_id, dep.number))
    try:
        lg.end(ok, "" if ok else "failed")
        total = f" · {fmt_seconds(time.time() - dep.started.timestamp())} in total" if dep.started else ""
        if ok:
            lg.line(f"\n{stamp()} ✓ Live{' — ' + note if note else ''}{total}")
        elif error == "Cancelled.":
            lg.line(f"\n{stamp()} ✗ Cancelled{total}")
        else:
            lg.line(f"\n{stamp()} ✗ Deployment failed: {error or 'unknown error'}{total}")
    finally:
        lg.close()
    now = timezone.now()
    if not ok:
        _mark(dep, "cancelled" if error == "Cancelled." else "failed", error=error[:1000], finished=now)
        return
    with transaction.atomic():
        Deployment.objects.filter(app_id=dep.app_id, status="live").exclude(pk=dep.pk).update(status="old")
        _mark(dep, "live", error="", finished=now)
        App.objects.filter(pk=dep.app_id).update(live=dep)
    prune(dep.app_id)


def prune(app_id: int) -> None:
    """Keep the newest few release folders (for quick rollbacks) and a bounded deploy history."""
    app = App.objects.filter(pk=app_id).first()
    if not app:
        return
    keep_numbers = set(app.deployments.filter(status__in=("live", "old")).values_list("number", flat=True)[:KEEP_RELEASES])
    if app.live_id:
        keep_numbers.add(app.live.number)
    busy = set(app.deployments.filter(status__in=("queued", "building", "starting")).values_list("number", flat=True))
    rel = core.releases_dir(app_id)
    if rel.is_dir():
        for d in rel.iterdir():
            if d.name.isdigit() and int(d.name) not in keep_numbers | busy:
                # A rollback reuses the folder of the deployment it goes back to.
                if app.deployments.filter(rollback_of=int(d.name), status__in=("live", "starting")).exists():
                    continue
                isolation.remove_tree(app_id, d)
    old = list(app.deployments.values_list("number", flat=True)[KEEP_DEPLOYS:])
    if old:
        app.deployments.filter(number__in=old).exclude(status__in=("live", "queued", "building", "starting")).delete()
        for n in old:
            core.deploy_log(app_id, n).unlink(missing_ok=True)
            plan_path(app_id, n).unlink(missing_ok=True)
            phases_path(app_id, n).unlink(missing_ok=True)


def recover() -> None:
    """After a worker restart: builds that were cut off are failed (the queue carries on)."""
    msg = "The apps service restarted during this deployment."
    for dep in Deployment.objects.filter(status__in=("building", "starting")).select_related("app"):
        lg = Log(core.deploy_log(dep.app_id, dep.number))
        try:
            lg.end(False, "interrupted")
            lg.line(f"\n{stamp()} ✗ {msg}")
        finally:
            lg.close()
    Deployment.objects.filter(status__in=("building", "starting")).update(status="failed", error=msg, finished=timezone.now())
    # Cancelled while building, and the worker went away before it noticed: the log is over.
    Deployment.objects.filter(status="cancelled", finished__isnull=True).update(finished=timezone.now())
