"""Kern CI: pipeline runs for hosted git repositories (docs/git-ci.md).

* A push listener queues a run for every pushed branch/tag whose commit has a ``.kern/ci.yml``
  matching its ``on`` section; the UI can queue manual runs and re-runs.
* ``manage.py ci_worker`` (:class:`Worker`) executes queued runs of every user, one at a time by default
  (``KERN_CI_CONCURRENCY``), through a runner from ``ci_runner`` (docker or shell).
* Logs and artifacts live in the user's data folder under ``ci/<run id>/``; only the newest
  ``KERN_CI_KEEP_RUNS`` runs per repository are kept. Secrets are per repository, encrypted with
  ``kern.secretbox``, injected only into jobs that list them and masked in logs.

Everything here runs with a user's tenant active (``kern.tenancy.use``).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from django.utils import timezone

from kern import secretbox, tenancy

from . import ci_pipeline as pl
from . import ci_runner as rn
from . import gitevents
from . import gitrepo as g
from .models_ci import CISecret, Job, Run

log = logging.getLogger("kern.ci")

MAX_SECRETS = 100
MAX_SECRET_BYTES = 64 * 1024
REF_RE = re.compile(r"^[A-Za-z0-9._/@+-]{1,200}$")


def keep_runs() -> int:
    try:
        return max(1, int(os.environ.get("KERN_CI_KEEP_RUNS", 50)))
    except ValueError:
        return 50


# ------------------------------------------------------------------ files


def ci_root() -> Path:
    return tenancy.data_dir() / "ci"


def run_dir(run_id: int) -> Path:
    return ci_root() / str(int(run_id))


def log_path(run_id: int, job: str) -> Path:
    return run_dir(run_id) / f"{job}.log"


def artifacts_dir(run_id: int, job: str | None = None) -> Path:
    d = run_dir(run_id) / "artifacts"
    return d / job if job else d


@dataclass(frozen=True)
class ArtifactFile:
    job: str
    name: str  # path inside the job's artifact folder, e.g. "dist/app.apk"
    path: Path  # the file on disk
    size: int


def run_artifacts(run) -> list[ArtifactFile]:
    """The artifact files of a finished run (empty while it is still queued or running), for
    other features such as releases. Call with the owner's tenant active."""
    if isinstance(run, int):
        run = Run.objects.filter(pk=run).first()
    if run is None or run.status not in Run.FINISHED:
        return []
    base = artifacts_dir(run.id)
    out = []
    if not base.is_dir():
        return out
    for job in sorted(p for p in base.iterdir() if p.is_dir()):
        for dirpath, _dirs, files in os.walk(job):
            for f in sorted(files):
                full = Path(dirpath) / f
                if full.is_symlink() or not full.is_file():
                    continue
                out.append(ArtifactFile(job.name, full.relative_to(job).as_posix(), full, full.stat().st_size))
    return out


def artifact_path(run_id: int, job: str, rel: str) -> Path | None:
    """The file of one artifact, or None. ``job`` and ``rel`` come from the URL: never trust them."""
    if not pl.JOB_RE.match(job or ""):
        return None
    parts = [x for x in (rel or "").split("/") if x]
    if not parts or any(x in (".", "..") or "\0" in x for x in parts):
        return None
    base = artifacts_dir(run_id, job).resolve()
    p = base.joinpath(*parts)
    try:
        if p.is_symlink() or not p.resolve().is_relative_to(base) or not p.is_file():
            return None
    except OSError:
        return None
    return p


def purge_run_files(run_id: int):
    shutil.rmtree(run_dir(run_id), ignore_errors=True)


def is_running(repo: str) -> bool:
    return Run.objects.filter(repo=repo, status=Run.RUNNING).exists()


def rename_repo(old: str, new: str):
    """The repository was renamed: its runs (queued ones too) and secrets follow."""
    Run.objects.filter(repo=old).update(repo=new)
    CISecret.objects.filter(repo=old).update(repo=new)


def purge_repo(repo: str):
    """Forget everything CI knows about a repository (it is being deleted)."""
    ids = list(Run.objects.filter(repo=repo).values_list("id", flat=True))
    for i in ids:
        purge_run_files(i)
    Run.objects.filter(repo=repo).delete()
    CISecret.objects.filter(repo=repo).delete()


def prune(repo: str):
    """Keep the newest ``keep_runs()`` runs of a repository; running ones are never removed."""
    rows = list(Run.objects.filter(repo=repo).order_by("-id").values_list("id", "status"))
    old = [i for i, st in rows[keep_runs():] if st in Run.FINISHED]
    if old:
        for i in old:
            purge_run_files(i)
        Run.objects.filter(pk__in=old).delete()


# --------------------------------------------------------------- pipelines


def load_pipeline(path: Path, sha: str):
    """(pipeline, error) of the commit: (None, None) when it has no pipeline file."""
    if not g.SHA_RE.match(sha):
        return None, None
    for fname in pl.PIPELINE_FILES:
        entry = g.text(path, "ls-tree", "-l", sha, "--", fname, check=False).strip()
        if not entry:
            continue
        meta, _, _name = entry.partition("\t")
        fields = meta.split()
        if len(fields) < 4 or fields[1] != "blob" or fields[0] not in ("100644", "100755"):
            return None, f"{fname} must be a regular file."
        try:
            if int(fields[3]) > pl.MAX_FILE_BYTES:
                return None, f"{fname} is larger than 256 KB."
        except ValueError:
            pass
        data = g.git(path, "cat-file", "blob", fields[2], check=False)
        try:
            return pl.parse(data), None
        except pl.PipelineError as e:
            return None, f"{fname}: {e}"
    return None, None


def _subject(path: Path, sha: str) -> str:
    try:
        return g.text(path, "log", "-1", "--format=%s", sha, "--", check=False).strip()[:300]
    except g.GitError:
        return ""


def create_run(repo: str, path: Path, ref: str, sha: str, trigger: str, pusher: str, pipeline, error: str = "") -> Run:
    now = timezone.now()
    run = Run.objects.create(repo=repo, ref=ref, sha=sha, subject=_subject(path, sha), trigger=trigger,
                             pusher=pusher[:150], pipeline=pipeline,
                             status=Run.ERROR if error else Run.QUEUED, error=error,
                             started=now if error else None, finished=now if error else None)
    if pipeline:
        for i, j in enumerate(pl.order(pipeline["jobs"])):
            Job.objects.create(run=run, name=j["name"], position=i)
    if trigger == "push" and not error:
        # A newer push to the same ref makes its queued (not yet running) runs pointless.
        old = Run.objects.filter(repo=repo, ref=ref, status=Run.QUEUED, trigger="push").exclude(pk=run.pk)
        ids = list(old.values_list("id", flat=True))
        if ids:
            Job.objects.filter(run_id__in=ids).update(status=Job.CANCELLED)
            old.update(status=Run.CANCELLED, finished=now, error="Superseded by a newer push.")
    prune(repo)
    return run


# ----------------------------------------------------------------- triggers


@gitevents.on_push
def on_push(event: gitevents.PushEvent):
    for up in event.updates:
        if up.deleted or not (up.branch or up.tag):
            continue
        try:
            pipeline, error = load_pipeline(event.path, up.new)
            if pipeline is None and not error:
                continue
            if pipeline is not None and not pl.push_matches(pipeline, up.branch, up.tag):
                continue
            create_run(event.repo, event.path, up.ref, up.new, "push", event.pusher, pipeline, error or "")
        except Exception:  # noqa: BLE001  (a broken pipeline must never break pushing)
            log.exception("could not queue a CI run for %s %s", event.repo, up.ref)


def resolve_ref(path: Path, ref: str) -> tuple[str, str]:
    """(full ref name, commit sha) of a branch or tag name."""
    ref = (ref or "").strip()
    if not REF_RE.match(ref) or ".." in ref or ref.startswith(("-", "/")):
        raise g.GitError("Invalid branch or tag name.")
    names = [ref] if ref.startswith(("refs/heads/", "refs/tags/")) else [f"refs/heads/{ref}", f"refs/tags/{ref}"]
    for full in names:
        sha = g.text(path, "rev-parse", "--verify", "--quiet", f"{full}^{{commit}}", check=False).strip()
        if g.SHA_RE.match(sha):
            return full, sha
    raise g.GitError("No such branch or tag.", 404)


def start_manual(repo: str, path: Path, ref: str, who: str) -> Run:
    full, sha = resolve_ref(path, ref)
    pipeline, error = load_pipeline(path, sha)
    if pipeline is None and not error:
        raise g.GitError("That commit has no .kern/ci.yml pipeline file.")
    if pipeline is not None and not pipeline["on"]["manual"]:
        raise g.GitError("Manual runs are turned off in the pipeline file (on: manual: false).")
    return create_run(repo, path, full, sha, "manual", who, pipeline, error or "")


def start_rerun(run: Run, path: Path, who: str) -> Run:
    if run.status not in Run.FINISHED:
        raise g.GitError("Only a finished run can be run again.", 409)
    pipeline = run.pipeline
    error = ""
    if pipeline is None:
        pipeline, error = load_pipeline(path, run.sha)
        if pipeline is None and not error:
            raise g.GitError("That commit has no pipeline file any more.")
    return create_run(run.repo, path, run.ref, run.sha, "rerun", who, pipeline, error or "")


def cancel(run: Run) -> Run:
    now = timezone.now()
    n = Run.objects.filter(pk=run.pk, status=Run.QUEUED).update(status=Run.CANCELLED, finished=now, error="Cancelled.")
    if n:
        Job.objects.filter(run=run).update(status=Job.CANCELLED)
    elif run.status == Run.RUNNING:
        Run.objects.filter(pk=run.pk).update(cancel_requested=True)
    else:
        raise g.GitError("That run has already finished.", 409)
    run.refresh_from_db()
    return run


def status_for_shas(repo: str, shas: list[str]) -> dict:
    shas = [s for s in dict.fromkeys(shas) if g.SHA_RE.match(s)][:200]
    out = {}
    for r in Run.objects.filter(repo=repo, sha__in=shas).order_by("id").values("id", "sha", "status"):
        out[r["sha"]] = {"status": r["status"], "run": r["id"]}
    return out


# ------------------------------------------------------------------ secrets


def secret_names(repo: str) -> list[dict]:
    return [{"name": s.name, "updated": s.updated.isoformat()} for s in CISecret.objects.filter(repo=repo).order_by("name")]


def set_secret(repo: str, name: str, value: str):
    if not pl.ENV_RE.match(name or "") or name.startswith("KERN_"):
        raise g.GitError("Secret names use letters, digits and underscores (max 64) and cannot start with KERN_.")
    if not isinstance(value, str) or not value:
        raise g.GitError("The secret needs a value.")
    if len(value.encode()) > MAX_SECRET_BYTES or "\0" in value:
        raise g.GitError("The secret is too large (64 KB at most) or contains a NUL byte.")
    if not CISecret.objects.filter(repo=repo, name=name).exists() and CISecret.objects.filter(repo=repo).count() >= MAX_SECRETS:
        raise g.GitError(f"At most {MAX_SECRETS} secrets per repository.")
    CISecret.objects.update_or_create(repo=repo, name=name, defaults={"value_enc": secretbox.encrypt(value)})


def delete_secret(repo: str, name: str) -> bool:
    return bool(CISecret.objects.filter(repo=repo, name=name).delete()[0])


def secret_values(repo: str, names: list[str]) -> dict:
    """Decrypted values of the named secrets of this repository only (missing ones are left out)."""
    rows = CISecret.objects.filter(repo=repo, name__in=names)
    return {r.name: secretbox.decrypt(r.value_enc) for r in rows}


# ---------------------------------------------------------------- execution


class _CancelPoll:
    def __init__(self, run_id):
        self.run_id, self.last, self.value = run_id, 0.0, False

    def __call__(self):
        if self.value:
            return True
        if time.monotonic() - self.last >= 0.5:
            self.last = time.monotonic()
            self.value = Run.objects.filter(pk=self.run_id, cancel_requested=True).exists()
        return self.value


def claim_next() -> Run | None:
    """Mark the oldest queued run of the active user as running and return it."""
    for r in Run.objects.filter(status=Run.QUEUED).order_by("id")[:5]:
        if Run.objects.filter(pk=r.pk, status=Run.QUEUED).update(status=Run.RUNNING, started=timezone.now()):
            r.refresh_from_db()
            return r
    return None


def recover() -> int:
    """After a crash: runs still marked running are over. Returns how many were fixed."""
    now = timezone.now()
    ids = list(Run.objects.filter(status=Run.RUNNING).values_list("id", flat=True))
    for i in ids:
        Job.objects.filter(run_id=i, status=Job.RUNNING).update(status=Job.ERROR, finished=now, note="The worker stopped.")
        Job.objects.filter(run_id=i, status=Job.PENDING).update(status=Job.SKIPPED, finished=now, note="The worker stopped.")
    Run.objects.filter(pk__in=ids).update(status=Run.ERROR, finished=now,
                                          error="The CI worker stopped while this run was in progress.")
    return len(ids)


def _checkout(path: Path, sha: str, dest: Path):
    cmd = ["git", f"--git-dir={path}", "archive", "--format=tar", f"--prefix={rn.WORKDIR}/", "--end-of-options", sha]
    with open(dest, "wb") as out:
        r = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, env=g.env(), timeout=600)
    if r.returncode != 0:
        raise rn.RunnerError("Could not read the commit: " + r.stderr.decode(errors="replace").strip()[:200])


def _kern_env(run: Run, job_name: str) -> dict:
    env = {"CI": "1", "KERN_CI": "1", "KERN_REPO": run.repo, "KERN_REF": run.ref, "KERN_SHA": run.sha,
           "KERN_RUN_ID": str(run.id), "KERN_JOB": job_name, "KERN_TRIGGER": run.trigger}
    if run.branch:
        env["KERN_BRANCH"] = run.branch
    if run.tag:
        env["KERN_TAG"] = run.tag
    return env


def _job_spec(run: Run, j: dict, secrets: dict) -> rn.JobSpec:
    lim = pl.limits()
    cap = lim["max"]
    steps = [rn.StepSpec(s["name"], s["run"], min(s["timeout"] * 60, cap) if s["timeout"] else None, s["env"])
             for s in j["steps"]]
    timeout = min((j["timeout"] * 60) if j["timeout"] else lim["default"], cap)
    return rn.JobSpec(
        name=j["name"], image=j["image"] or pl.default_image(),
        env=j["env"] | secrets | _kern_env(run, j["name"]),
        steps=steps, timeout=timeout, artifacts=j["artifacts"],
        labels={"kern.ci.run": run.id, "kern.ci.repo": run.repo, "kern.ci.job": j["name"],
                "kern.ci.uid": tenancy.current_uid() or 0},
    )


def execute(run: Run, runner_factory=None) -> Run:
    """Run every job of a claimed (running) run and record the outcome."""
    runner_factory = runner_factory or rn.get_runner
    cancelled = _CancelPoll(run.id)
    work = Path(tempfile.mkdtemp(prefix="kern-ci-co-"))
    jobs = {j.name: j for j in run.jobs.all()}
    result: dict[str, str] = {}
    try:
        try:
            path = g.repo_path(run.repo)
            run_dir(run.id).mkdir(parents=True, exist_ok=True)
            pipeline = run.pipeline
            if not pipeline:
                raise rn.RunnerError("The run has no pipeline.")
            tar = work / "checkout.tar"
            _checkout(path, run.sha, tar)
        except (rn.RunnerError, g.GitError, OSError, subprocess.SubprocessError) as e:
            return _finish(run, Run.ERROR, f"Could not prepare the run: {e}", jobs)

        for j in pl.order(pipeline["jobs"]):
            row = jobs[j["name"]]
            if cancelled():
                break
            lg = rn.LogWriter(log_path(run.id, j["name"]))
            try:
                blocker = next((n for n in j["needs"] if result.get(n) != Job.SUCCESS), None)
                if blocker:
                    _mark(row, Job.SKIPPED, f"needs {blocker}, which did not succeed")
                    lg.line(f"[kern-ci] skipped: needs {blocker}, which did not succeed")
                elif not pl.job_enabled(j, run.branch, run.tag):
                    _mark(row, Job.SKIPPED, "condition not met")
                    lg.line("[kern-ci] skipped: the if condition does not match this ref")
                else:
                    _run_job(run, j, row, tar, lg, runner_factory, cancelled)
            finally:
                lg.close()
            row.refresh_from_db()
            result[j["name"]] = row.status

        now = timezone.now()
        for row in jobs.values():
            row.refresh_from_db()
            if row.status == Job.PENDING:
                row.status, row.finished = Job.CANCELLED, now
                row.note = "cancelled"
                row.save(update_fields=["status", "finished", "note"])
        statuses = {r.status for r in jobs.values()}
        if cancelled() or Job.CANCELLED in statuses:
            final = Run.CANCELLED
        elif Job.FAILED in statuses:
            final = Run.FAILED
        elif Job.ERROR in statuses:
            final = Run.ERROR
        else:
            final = Run.SUCCESS
        return _finish(run, final, "", None)
    except Exception as e:  # noqa: BLE001
        log.exception("CI run %s crashed", run.id)
        return _finish(run, Run.ERROR, f"Internal error: {e}", jobs)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            prune(run.repo)
        except Exception:  # noqa: BLE001
            log.exception("pruning CI runs failed")


def _mark(row: Job, status: str, note: str = "", exit_code=None, start=None):
    row.status, row.note, row.exit_code = status, note[:300], exit_code
    if start:
        row.started = start
    row.finished = timezone.now()
    row.save()


def _run_job(run: Run, j: dict, row: Job, tar: Path, lg: rn.LogWriter, runner_factory, cancelled):
    row.status, row.started = Job.RUNNING, timezone.now()
    row.save(update_fields=["status", "started"])
    try:
        wanted = secret_values(run.repo, j["secrets"])
    except secretbox.SecretBoxError as e:
        lg.line(f"[kern-ci] {e}")
        return _mark(row, Job.ERROR, str(e), start=row.started)
    missing = [s for s in j["secrets"] if s not in wanted]
    lg.set_secrets(list(wanted.values()))
    if missing:
        lg.line(f"[kern-ci] the secret(s) {', '.join(missing)} are not set for this repository (Settings → CI secrets)")
        return _mark(row, Job.FAILED, f"secret {missing[0]} is not set", start=row.started)
    spec = _job_spec(run, j, wanted)
    try:
        runner = runner_factory()
        out = runner.run(spec, tar, lg, cancelled, artifacts_dir(run.id, j["name"]))
    except rn.RunnerError as e:
        lg.line(f"[kern-ci] error: {e}")
        out = rn.JobOutcome("error", note=str(e)[:290])
    _mark(row, {"success": Job.SUCCESS, "failed": Job.FAILED, "cancelled": Job.CANCELLED}.get(out.status, Job.ERROR),
          out.note, out.exit_code, start=row.started)


def _finish(run: Run, status: str, error: str, jobs: dict | None) -> Run:
    now = timezone.now()
    if jobs:
        for row in jobs.values():
            row.refresh_from_db()
            if row.status in (Job.PENDING, Job.RUNNING):
                row.status = Job.SKIPPED if row.status == Job.PENDING else Job.ERROR
                row.finished, row.note = now, "run aborted"
                row.save(update_fields=["status", "finished", "note"])
    Run.objects.filter(pk=run.pk).update(status=status, error=error, finished=now)
    run.refresh_from_db()
    try:
        _publish(run)
    except Exception:  # noqa: BLE001  (a failed hand-off never changes the run's result)
        log.exception("publishing CI run %s failed", run.id)
    return run


def _publish(run: Run) -> None:
    """After a run: attach `release: true` jobs' artifacts to the tag's release (successful tag
    runs only), then tell the repository's webhooks (event "ci_run")."""
    if run.status == Run.SUCCESS and run.tag and run.pipeline:
        wanted = {j["name"] for j in run.pipeline.get("jobs", []) if j.get("release")}
        ok = {j.name for j in run.jobs.all() if j.status == Job.SUCCESS}
        files = [f for f in run_artifacts(run) if f.job in wanted & ok]
        if files:
            from . import git_releases
            for f in files:
                git_releases.attach_file(run.repo, run.tag, f.name.rsplit("/", 1)[-1], f.path, create=True)
            for job in wanted & ok:
                with open(log_path(run.id, job), "a") as lf:
                    n = sum(1 for f in files if f.job == job)
                    lf.write(f"[kern-ci] attached {n} file(s) to the release of {run.tag}\n")
    uid = tenancy.current_uid()
    if uid is not None:
        from . import gitwebhooks
        gitwebhooks.emit(uid, run.repo, "ci_run", lambda: {
            "run": {"id": run.id, "status": run.status, "ref": run.ref, "sha": run.sha, "trigger": run.trigger,
                    "pusher": run.pusher, "error": run.error,
                    "started": run.started.isoformat() if run.started else None,
                    "finished": run.finished.isoformat() if run.finished else None,
                    "jobs": [{"name": j.name, "status": j.status} for j in run.jobs.all()]},
        })


def _register_events():
    from . import gitwebhooks
    gitwebhooks.register_event("ci_run", "CI run finished")


_register_events()


def drain(runner_factory=None) -> int:
    """Run every queued run of the active user, one after another (tests, one-off use)."""
    n = 0
    while (r := claim_next()):
        execute(r, runner_factory)
        n += 1
    return n


# ------------------------------------------------------------------- worker


def concurrency() -> int:
    try:
        return max(1, int(os.environ.get("KERN_CI_CONCURRENCY", 1)))
    except ValueError:
        return 1


class Worker:
    """Loops over all users, running queued runs (``manage.py ci_worker``)."""

    def __init__(self, runner_factory=None, poll=None):
        self.runner_factory = runner_factory or rn.get_runner
        self.poll = poll if poll is not None else float(os.environ.get("KERN_CI_POLL_SECONDS", 2))
        self.stopping = threading.Event()
        self.active: dict[threading.Thread, int] = {}

    def users(self):
        from django.contrib.auth.models import User

        for u in User.objects.filter(is_active=True).order_by("id"):
            if tenancy.testing() or tenancy.user_dir(u.id).is_dir():
                yield u.id

    def startup(self):
        try:
            r = self.runner_factory()
            if isinstance(r, rn.DockerRunner):
                n = r.cleanup_stale()
                if n:
                    log.info("removed %s stale CI container(s)", n)
        except rn.RunnerError as e:
            log.warning("could not clean up CI containers: %s", e)
        for uid in self.users():
            with tenancy.use(uid):
                n = recover()
                if n:
                    log.warning("user %s: %s run(s) were interrupted by a restart", uid, n)

    def next_run(self):
        best = None
        for uid in self.users():
            with tenancy.use(uid):
                r = Run.objects.filter(status=Run.QUEUED).order_by("id").values("id", "created").first()
            if r and (best is None or r["created"] < best[1]):
                best = (uid, r["created"])
        if best:
            with tenancy.use(best[0]):
                run = claim_next()
            if run:
                return best[0], run
        return None

    def _go(self, uid, run):
        try:
            with tenancy.use(uid):
                execute(run, self.runner_factory)
        except Exception:  # noqa: BLE001
            log.exception("CI run %s failed", run.id)
        finally:
            tenancy.close_connections()

    def tick(self):
        self.active = {t: u for t, u in self.active.items() if t.is_alive()}
        while len(self.active) < concurrency() and not self.stopping.is_set():
            nxt = self.next_run()
            if not nxt:
                break
            uid, run = nxt
            t = threading.Thread(target=self._go, args=(uid, run), daemon=True, name=f"ci-run-{run.id}")
            self.active[t] = uid
            t.start()

    def run_forever(self):
        self.startup()
        log.info("CI worker started (runner=%s, concurrency=%s)", os.environ.get("KERN_CI_RUNNER", "docker"), concurrency())
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("CI worker loop failed")
                tenancy.close_connections()
            self.stopping.wait(self.poll)
        for t in list(self.active):
            t.join(timeout=30)
