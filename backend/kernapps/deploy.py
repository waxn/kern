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


class Log:
    """The deploy log: plain text lines, the newest deployment's is what the UI streams."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8", errors="replace")

    def line(self, text: str):
        self.fh.write(text.rstrip("\n") + "\n")
        self.fh.flush()

    def step(self, text: str):
        self.line(f"\n▸ {text}")

    def close(self):
        self.fh.close()


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


def _run_step(app: App, cmd: str, cwd: Path, env: dict, lg: Log, cancelled) -> None:
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
            raise DeployError("Cancelled.")
        raise DeployError(f"“{cmd}” took longer than {BUILD_TIMEOUT // 60} minutes.")
    if p.returncode:
        raise DeployError(f"“{cmd}” failed (exit code {p.returncode}). See the build log.")


def build(dep: Deployment, cancelled=lambda: False) -> tuple[core.Plan, Path]:
    """Prepare the release folder of ``dep``. Returns (plan, release). Raises DeployError."""
    app = dep.app
    lg = Log(core.deploy_log(app.id, dep.number))
    _mark(dep, "building", started=timezone.now())
    try:
        try:
            isolation.prepare(app.id)
        except isolation.IsolationError as e:
            raise DeployError(str(e))
        if dep.rollback_of:
            release = core.release_dir(app.id, dep.rollback_of)
            plan = load_plan(app.id, dep.rollback_of)
            if not release.is_dir() or plan is None:
                raise DeployError(f"The files of deployment #{dep.rollback_of} are gone (only the newest "
                                  f"{KEEP_RELEASES} are kept). Deploy that commit again instead.")
            lg.step(f"Going back to deployment #{dep.rollback_of} ({dep.sha[:10]})")
            plan_path(app.id, dep.number).write_text(json.dumps(plan.as_json()))
            _mark(dep, "starting", runtime=plan.runtime)
            return plan, release

        lg.step("Getting the code")
        try:
            gd = source.git_dir(app)
            if app.source == "url":
                lg.line(f"Fetched {app.git_url} ({app.branch})")
            sha, subject = source.resolve(app, gd, dep.sha or None)
        except source.SourceError as e:
            raise DeployError(str(e))
        _mark(dep, "building", sha=sha, subject=dep.subject or subject)
        lg.line(f"Commit {sha[:10]} · {dep.subject or subject}")
        release = core.release_dir(app.id, dep.number)
        isolation.remove_tree(app.id, release)
        try:
            source.export(app, gd, sha, release)
        except source.SourceError as e:
            raise DeployError(str(e))

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
        if steps:
            lg.step("Building")
        for i, cmd in enumerate(steps):
            # The environment is made again for each step, so a fresh .venv or node_modules is on PATH.
            env = core.build_env(app, release, home)
            _run_step(app, cmd, release, env, lg, cancelled)
        if plan.runtime == "static":
            root = core.static_root(release, plan)
            if not (root / "index.html").is_file():
                raise DeployError(f"There is no index.html to serve (looked in {root.relative_to(release) or 'the app folder'}).")
        plan_path(app.id, dep.number).write_text(json.dumps(plan.as_json()))
        _mark(dep, "starting", runtime=plan.runtime)
        lg.step("Starting")
        return plan, release
    except DeployError as e:
        lg.line(f"\n✗ {e}")
        raise
    except Exception as e:  # a bug of ours: still end the deployment cleanly
        log.exception("deploy %s failed", dep.pk)
        lg.line(f"\n✗ Kern hit an error: {e}")
        raise DeployError(f"Kern hit an error while deploying: {e}")
    finally:
        lg.close()


def finish(dep: Deployment, ok: bool, error: str = "") -> None:
    """Record the outcome. On success this deployment becomes the app's live one."""
    lg = Log(core.deploy_log(dep.app_id, dep.number))
    try:
        if ok:
            lg.line("✓ Live")
        elif error:
            lg.line(f"\n✗ {error}")
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


def recover() -> None:
    """After a worker restart: builds that were cut off are failed (the queue carries on)."""
    Deployment.objects.filter(status__in=("building", "starting")).update(
        status="failed", error="The apps service restarted during this deployment.", finished=timezone.now())
