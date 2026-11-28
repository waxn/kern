"""The apps API (``/api/apps/…``): create, configure, start and stop apps, deploy, read logs, edit files
and talk to the AI builder. Every app belongs to one user and only that user can see or change it."""
from __future__ import annotations

import functools
import io
import os
import re
import tarfile
from pathlib import Path

import requests
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from kern import tenancy
from notes import gitrepo as g
from notes import remote_guard

from . import core, dbexplore, deploy, source, starters, tasks as tasks_mod
from .models import App, BuilderChat, Deployment

MAX_LOG_CHUNK = 256 * 1024


class ApiError(Exception):
    def __init__(self, msg, status=400, **extra):
        super().__init__(msg)
        self.status = status
        self.extra = extra


def bad(msg, status=400, **extra):
    return Response({"detail": msg, **extra}, status=status)


def handle(fn):
    @functools.wraps(fn)
    def wrapper(request, *args, **kwargs):
        if not core.can_use(request.user):
            return bad("Apps are not available for your account. An administrator can turn them on in Settings → Server.", 403)
        try:
            return fn(request, *args, **kwargs)
        except ApiError as e:
            return bad(str(e), e.status, **e.extra)
        except dbexplore.DbError as e:
            return bad(str(e), e.status)
        except (source.SourceError, core.PlanError, ValueError) as e:
            return bad(str(e))
        except g.GitError as e:
            return bad(str(e), e.status)
        except remote_guard.RemoteNotAllowed as e:
            return bad(str(e))
    return wrapper


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _app(request, slug: str) -> App:
    a = App.objects.select_related("live").filter(slug=slug, owner=request.user.id).first()
    if a is None:
        raise ApiError("No such app.", 404)
    return a


# --------------------------------------------------------------------- worker


def worker_status() -> dict | None:
    try:
        r = requests.get(core.control_url() + "/status", headers={"X-Kern-Control": core.control_token()}, timeout=1.5)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def worker_get(path: str, timeout=3) -> dict | None:
    try:
        r = requests.get(core.control_url() + path, headers={"X-Kern-Control": core.control_token()}, timeout=timeout)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def worker_post(path: str, json=None, timeout=3) -> dict | None:
    try:
        r = requests.post(core.control_url() + path, headers={"X-Kern-Control": core.control_token()}, json=json or {}, timeout=timeout)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


# ------------------------------------------------------------------------ JSON


def _iso(d):
    return d.isoformat() if d else None


def deploy_json(d: Deployment) -> dict:
    return {
        "number": d.number, "sha": d.sha, "short": d.sha[:8], "subject": d.subject, "trigger": d.trigger, "who": d.who,
        "status": d.status, "error": d.error, "runtime": d.runtime, "rollback_of": d.rollback_of,
        "created": _iso(d.created), "started": _iso(d.started), "finished": _iso(d.finished),
        "seconds": int((d.finished - d.started).total_seconds()) if d.finished and d.started else None,
    }


def app_json(a: App, live: dict | None = None, full=False) -> dict:
    out = {
        "id": a.id, "slug": a.slug, "name": a.name, "description": a.description, "icon": a.icon, "color": a.color,
        "path": f"/{a.slug}/", "access": a.access, "enabled": a.enabled, "state": a.state, "state_detail": a.state_detail,
        "state_at": _iso(a.state_at), "source": a.source, "repo": a.repo, "git_url": a.git_url, "branch": a.branch,
        "subdir": a.subdir, "auto_deploy": a.auto_deploy, "created": _iso(a.created), "updated": _iso(a.updated),
        "live": deploy_json(a.live) if a.live_id and a.live else None,
        "metrics": live, "runtime": a.runtime or (a.live.runtime if a.live_id and a.live else ""),
    }
    latest = a.deployments.order_by("-number").first()
    out["latest"] = deploy_json(latest) if latest else None
    if full:
        out.update({
            "build_cmd": a.build_cmd, "start_cmd": a.start_cmd, "health_path": a.health_path, "runtime_setting": a.runtime,
            "public_paths": a.public_paths or [], "strip_prefix": a.strip_prefix, "has_token": bool(a.git_token_enc),
            "hook_path": f"/_apps/hook/{a.id}/{a.hook_secret}", "env_names": sorted(core.get_env(a)),
        })
    return out


def _live_of(status: dict | None, a: App):
    if status is None:
        return None
    return (status.get("apps") or {}).get(str(a.id))


# ------------------------------------------------------------------------ list


@api_view(["GET", "POST"])
@handle
def apps(request):
    if request.method == "POST":
        return Response(create(request, _body(request)), status=201)
    st = worker_status()
    rows = App.objects.select_related("live").filter(owner=request.user.id)
    return Response({
        "apps": [app_json(a, _live_of(st, a)) for a in rows],
        "worker": st is not None, "isolated": bool(st and st.get("isolated")),
    })


@api_view(["GET"])
@handle
def templates(request):
    return Response(starters.all_starters())


@api_view(["GET"])
@handle
def check_slug(request):
    slug = str(request.query_params.get("slug") or "").strip().lower()
    problem = core.slug_problem(slug)
    if not problem and App.objects.filter(slug=slug).exclude(owner=request.user.id, slug=request.query_params.get("current", "")).exists():
        problem = f"“/{slug}” is taken by another app."
    return Response({"ok": not problem, "problem": problem, "suggestion": core.suggest_slug(slug) if problem else slug})


def _free_repo_name(base: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base)[:56] or "app"
    name, n = base, 2
    while (g.root() / f"{name}.git").exists():
        name, n = f"{base}-{n}", n + 1
    return name


def create(request, data: dict) -> dict:
    name = str(data.get("name") or "").strip()[:80]
    if not name:
        raise ApiError("Give the app a name.")
    slug = str(data.get("slug") or core.suggest_slug(name)).strip().lower()
    problem = core.slug_problem(slug)
    if problem:
        raise ApiError(problem)
    if App.objects.filter(slug=slug).exists():
        raise ApiError(f"“/{slug}” is taken by another app.", 409)
    kind = data.get("kind")
    if kind not in ("template", "repo", "url", "ai"):
        raise ApiError("Choose how to start: a template, a repository, a git URL or the AI builder.")
    if kind == "ai":
        from notes import ai

        if not ai.public_config()["configured"]:
            raise ApiError("The AI assistant is not set up yet. Choose a provider in Settings → AI.", 409)
    a = App(owner=request.user.id, slug=slug, name=name, description=str(data.get("description") or "")[:300],
            icon=str(data.get("icon") or "")[:16], secret=core.new_secret(), hook_secret=core.new_secret(),
            access=data.get("access") if data.get("access") in ("private", "users", "public") else "private")
    files = None
    if kind == "template":
        st = starters.get(str(data.get("template") or ""))
        if st is None:
            raise ApiError("Unknown template.")
        files = starters.files(st["key"])
        a.icon = a.icon or st["icon"]
        a.public_paths = st["public_paths"]
        a.description = a.description or st["description"][:300]
    if kind in ("template", "ai"):
        a.source = "kern"
        a.repo = _free_repo_name(f"app-{slug}")
        g.create(a.repo, f"Source of the app “{name}” (/{slug}/)")
        a.branch = "main"
    elif kind == "repo":
        repo = str(data.get("repo") or "")
        g.repo_path(repo)  # exists?
        a.source, a.repo = "kern", repo
        a.branch = str(data.get("branch") or "").strip() or g.default_branch(g.repo_path(repo)) or "main"
        a.subdir = str(data.get("subdir") or "").strip().strip("/")[:200]
    else:
        info = remote_guard.check_url(str(data.get("git_url") or ""), http="local")
        a.source, a.git_url = "url", info["url"]
        a.branch = str(data.get("branch") or "").strip() or "main"
        a.subdir = str(data.get("subdir") or "").strip().strip("/")[:200]
        core.set_token(a, str(data.get("git_token") or "").strip())
    if not re.match(r"^[A-Za-z0-9._/@+-]{1,200}$", a.branch):
        raise ApiError("That branch name isn't valid.")
    try:
        a.save()
    except IntegrityError:
        raise ApiError(f"“/{slug}” is taken by another app.", 409)
    isolation_ready(a)
    if files:
        sha = source.commit(a, files, f"Start from the {starters.get(data['template'])['name']} template",
                            request.user.username, "kern:create")
        deploy.queue(a, "create", request.user.username, sha=sha)
    elif kind in ("repo", "url"):
        deploy.queue(a, "create", request.user.username)
    if kind == "ai":
        a.state = "new"
        a.save(update_fields=["state"])
        prompt = str(data.get("prompt") or "").strip()
        if prompt:
            _builder_send(a, prompt, request.user)
    a.refresh_from_db()
    return app_json(a, full=True)


def isolation_ready(a: App):
    """Make the folders now so the first deployment does not wait on it (the worker repeats this)."""
    try:
        core.logs_dir(a.id).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------- detail

EDITABLE = {"name", "description", "icon", "color", "access", "public_paths", "strip_prefix", "branch", "subdir",
            "auto_deploy", "runtime", "build_cmd", "start_cmd", "health_path", "git_url", "git_token", "slug", "repo"}


@api_view(["GET", "PATCH", "DELETE"])
@handle
def app_detail(request, slug):
    a = _app(request, slug)
    if request.method == "DELETE":
        if a.source == "kern" and _body(request).get("delete_repo") and a.repo:
            with tenancy.use(a.owner):
                try:
                    g.delete(a.repo)
                except g.GitError:
                    pass
        BuilderChat.objects.filter(app=a).delete()
        a.delete()  # the worker stops it and removes its folder at its next look
        deploy.kick()
        return Response(status=204)
    if request.method == "PATCH":
        data = {k: v for k, v in _body(request).items() if k in EDITABLE}
        if "name" in data:
            a.name = str(data["name"] or "").strip()[:80] or a.name
        if "description" in data:
            a.description = str(data["description"] or "").strip()[:300]
        if "icon" in data:
            a.icon = str(data["icon"] or "")[:16]
        if "color" in data:
            a.color = str(data["color"] or "")[:12]
        if "access" in data:
            if data["access"] not in ("private", "users", "public"):
                raise ApiError("Access is private, users or public.")
            a.access = data["access"]
        if "public_paths" in data:
            a.public_paths = core.clean_public_paths(data["public_paths"] if isinstance(data["public_paths"], list) else [])
        for k in ("strip_prefix", "auto_deploy"):
            if k in data:
                setattr(a, k, bool(data[k]))
        if "branch" in data:
            b = str(data["branch"] or "").strip()
            if not re.match(r"^[A-Za-z0-9._/@+-]{1,200}$", b):
                raise ApiError("That branch name isn't valid.")
            a.branch = b
        if "subdir" in data:
            a.subdir = str(data["subdir"] or "").strip().strip("/")[:200]
            if ".." in a.subdir.split("/"):
                raise ApiError("The folder can't contain “..”.")
        if "runtime" in data:
            if data["runtime"] not in ("", *core.RUNTIME_NAMES):
                raise ApiError("Unknown runtime.")
            a.runtime = data["runtime"]
        for k in ("build_cmd", "start_cmd"):
            if k in data:
                setattr(a, k, str(data[k] or "").strip()[:500])
        if "health_path" in data:
            hp = str(data["health_path"] or "").strip()[:200]
            if hp and not hp.startswith("/"):
                hp = "/" + hp
            a.health_path = hp
        if "git_url" in data and a.source == "url":
            a.git_url = remote_guard.check_url(str(data["git_url"] or ""), http="local")["url"]
        if "git_token" in data and a.source == "url":
            core.set_token(a, str(data["git_token"] or "").strip())
        if "repo" in data and a.source == "kern":
            with tenancy.use(a.owner):
                g.repo_path(str(data["repo"]))
            a.repo = str(data["repo"])
        if "slug" in data and data["slug"] != a.slug:
            new = str(data["slug"] or "").strip().lower()
            problem = core.slug_problem(new)
            if problem:
                raise ApiError(problem)
            if App.objects.filter(slug=new).exclude(pk=a.pk).exists():
                raise ApiError(f"“/{new}” is taken by another app.", 409)
            a.slug = new
        a.save()
        deploy.kick()
    st = worker_status()
    return Response({**app_json(a, _live_of(st, a), full=True), "worker": st is not None,
                     "isolated": bool(st and st.get("isolated"))})


# --------------------------------------------------------------------- actions


@api_view(["POST"])
@handle
def app_action(request, slug, action):
    a = _app(request, slug)
    if action == "start":
        a.enabled = True
        a.save(update_fields=["enabled", "updated"])
        worker_post(f"/restart/{a.id}")  # also clears a "crashed too often" hold
        if not a.live_id and not a.deployments.filter(status__in=("queued", "building")).exists():
            deploy.queue(a, "manual", request.user.username)
    elif action == "stop":
        a.enabled = False
        a.save(update_fields=["enabled", "updated"])
        deploy.kick()
    elif action == "restart":
        a.enabled = True
        a.save(update_fields=["enabled", "updated"])
        if worker_post(f"/restart/{a.id}") is None:
            raise ApiError("The apps service is not running, so nothing can be restarted.", 503)
    elif action == "deploy":
        deploy.queue(a, "manual", request.user.username, sha=str(_body(request).get("sha") or "")[:64])
    else:
        raise ApiError("Unknown action.", 404)
    a.refresh_from_db()
    st = worker_status()
    return Response(app_json(a, _live_of(st, a), full=True))


@api_view(["GET"])
@handle
def deploys(request, slug):
    a = _app(request, slug)
    return Response([deploy_json(d) for d in a.deployments.all()[:50]])


def _decode(chunk: bytes) -> tuple[str, int]:
    for cut in range(len(chunk), max(len(chunk) - 4, -1), -1):
        try:
            return chunk[:cut].decode("utf-8"), cut
        except UnicodeDecodeError:
            continue
    return chunk.decode("utf-8", "replace"), len(chunk)


def _read_from(p: Path, offset: int | None, tail: int = 64 * 1024) -> dict:
    """``offset`` None: the last ``tail`` bytes (starting at a line). Otherwise what came after offset."""
    try:
        size = p.stat().st_size
    except OSError:
        return {"text": "", "offset": 0, "size": 0}
    if offset is None:
        offset = max(0, size - tail)
    if offset > size:  # rotated
        offset = 0
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read(MAX_LOG_CHUNK)
    if offset and data and offset == max(0, size - tail):
        nl = data.find(b"\n")
        if 0 <= nl < len(data) - 1:
            data, offset = data[nl + 1:], offset + nl + 1
    text, used = _decode(data)
    return {"text": text, "offset": offset + used, "size": size}


def _offset(request):
    v = request.query_params.get("offset")
    if v in (None, ""):
        return None
    try:
        return max(0, int(v))
    except ValueError:
        raise ApiError("Invalid offset.")


@api_view(["GET"])
@handle
def deploy_log(request, slug, number):
    a = _app(request, slug)
    d = a.deployments.filter(number=number).first()
    if d is None:
        raise ApiError("No such deployment.", 404)
    out = _read_from(core.deploy_log(a.id, d.number), _offset(request) or 0, tail=10 ** 9)
    out["status"] = d.status
    # Over only when the worker has recorded the end (``finished``: it writes the last lines of the log first;
    # a build cancelled from here is "cancelled" long before the worker has stopped writing) and the
    # reader has everything that was written.
    over = d.status not in ("queued", "building", "starting") and d.finished is not None
    out["done"] = over and out["offset"] >= out["size"]
    out["deploy"] = deploy_json(d)
    # Phases of the deployment, recorded next to the log (see deploy.Log): [{name, status, started, seconds, detail}].
    out["phases"] = deploy.read_phases(a.id, d.number, finished=over)
    return Response(out)


@api_view(["POST"])
@handle
def deploy_action(request, slug, number, action):
    a = _app(request, slug)
    d = a.deployments.filter(number=number).first()
    if d is None:
        raise ApiError("No such deployment.", 404)
    if action == "cancel":
        if d.status == "queued":
            Deployment.objects.filter(pk=d.pk).update(status="cancelled", finished=timezone.now(), error="Cancelled.")
        elif d.status == "building":
            Deployment.objects.filter(pk=d.pk).update(status="cancelled")  # the worker stops the build
        return Response(deploy_json(Deployment.objects.get(pk=d.pk)))
    if action == "rollback":
        if d.status not in ("old", "live"):
            raise ApiError("Only a deployment that went live can be brought back.")
        target = d.rollback_of or d.number
        if not core.release_dir(a.id, target).is_dir():
            raise ApiError(f"The files of deployment #{d.number} are gone (Kern keeps the newest {deploy.KEEP_RELEASES}). "
                           "Deploy its commit again instead.", 410, sha=d.sha)
        new = deploy.queue(a, "rollback", request.user.username, sha=d.sha, subject=d.subject, rollback_of=target)
        a.enabled = True
        a.save(update_fields=["enabled", "updated"])
        return Response(deploy_json(new))
    raise ApiError("Unknown action.", 404)


@api_view(["GET", "DELETE"])
@handle
def app_logs(request, slug):
    a = _app(request, slug)
    p = core.app_log(a.id)
    if request.method == "DELETE":
        for f in (p, p.with_suffix(".log.1")):
            try:
                f.write_text("")
            except OSError:
                pass
        return Response(status=204)
    return Response(_read_from(p, _offset(request)))


# ------------------------------------------------------------------ tasks, database


@api_view(["GET"])
@handle
def app_tasks(request, slug):
    """What the app is running: its processes, the deployment in progress, the ones waiting, the builder."""
    a = _app(request, slug)
    st = worker_status()
    live = _live_of(st, a)
    procs = None
    if live and live.get("running") and live.get("pid"):
        r = worker_get(f"/processes/{a.id}")
        procs = r.get("processes") if isinstance(r, dict) else None
    return Response(tasks_mod.build(a, live, procs, worker_up=st is not None))


def _db_file(request, body=None) -> str:
    src = body if body is not None else request.query_params
    return str(src.get("file") or "").strip()


@api_view(["GET"])
@handle
def app_db(request, slug):
    """The SQLite files in the app's data folder and the tables of one of them (read-only)."""
    a = _app(request, slug)
    return Response(dbexplore.overview(a.id, _db_file(request) or None))


@api_view(["GET"])
@handle
def app_db_rows(request, slug):
    a = _app(request, slug)
    q = request.query_params
    table = str(q.get("table") or "")
    if not table:
        raise ApiError("Say which table.")
    try:
        offset, limit = int(q.get("offset") or 0), int(q.get("limit") or 50)
    except ValueError:
        raise ApiError("offset and limit are numbers.")
    rel = dbexplore.pick_file(a.id, _db_file(request))
    return Response(dbexplore.table_rows(a.id, rel, table, offset, limit, q.get("order") or None, str(q.get("dir") or "asc")))


@api_view(["POST"])
@handle
def app_db_query(request, slug):
    """Run one read-only statement (SELECT, WITH, EXPLAIN, a few PRAGMAs) on a database file."""
    a = _app(request, slug)
    body = _body(request)
    rel = dbexplore.pick_file(a.id, _db_file(request, body))
    return Response(dbexplore.run_query(a.id, rel, body.get("sql")))


# ------------------------------------------------------------------------ env


@api_view(["GET", "PUT"])
@handle
def app_env(request, slug):
    a = _app(request, slug)
    if request.method == "PUT":
        vars_ = _body(request).get("vars")
        if not isinstance(vars_, dict):
            raise ApiError("Send vars as an object.")
        core.set_env(a, vars_)
        a.save(update_fields=["env_enc", "updated"])
        if _body(request).get("restart") and a.enabled:
            worker_post(f"/restart/{a.id}")
    env = core.get_env(a)
    return Response({"vars": [{"name": k, "value": v} for k, v in sorted(env.items())],
                     "builtin": sorted(core.OWN_ENV)})


# ---------------------------------------------------------------------- app AI


@api_view(["GET", "PUT"])
@handle
def app_ai(request, slug):
    """The provider and model the builder uses for this app; without one it follows the workspace settings."""
    from notes import ai

    a = _app(request, slug)
    with tenancy.use(a.owner):
        if request.method == "PUT":
            try:
                return Response(ai.save_config(_body(request), a.slug))
            except ai.AIError as e:
                return bad(str(e), e.status)
        return Response(ai.public_config(a.slug))


@api_view(["POST"])
@handle
def app_ai_models(request, slug):
    """The models this app's provider serves, detected before the settings are saved."""
    from notes import ai

    a = _app(request, slug)
    body = _body(request)
    with tenancy.use(a.owner):
        try:
            models = ai.list_models(
                str(body.get("provider") or ""),
                str(body.get("base_url") or ""),
                str(body.get("api_key") or ""),
                a.slug,
            )
        except ai.AIError as e:
            return bad(str(e), e.status)
    return Response({"models": models})


# ---------------------------------------------------------------------- files


def _head(a: App) -> tuple[Path, str | None]:
    gd = source.git_dir(a, fetch=False)
    if not (gd / "HEAD").is_file():
        return gd, None
    try:
        sha, _ = source.resolve(a, gd)
    except source.SourceError:
        return gd, None
    return gd, sha


@api_view(["GET", "PUT", "DELETE"])
@handle
def app_files(request, slug):
    a = _app(request, slug)
    if request.method in ("PUT", "DELETE"):
        data = _body(request)
        rel = source.clean_rel(str(data.get("path") or request.query_params.get("path") or ""))
        if request.method == "PUT":
            content = data.get("content")
            if not isinstance(content, str):
                raise ApiError("Send the file content as text.")
            changes = {rel: content}
            old = str(data.get("old_path") or "")
            if old and old != rel:
                changes[source.clean_rel(old)] = None
            msg = str(data.get("message") or "").strip() or f"Edit {rel}"
        else:
            changes, msg = {rel: None}, str(data.get("message") or "").strip() or f"Delete {rel}"
        sha = source.commit(a, changes, msg, request.user.username, "kern:" + request.user.username)
        if not a.auto_deploy and data.get("deploy"):
            deploy.queue(a, "edit", request.user.username, sha=sha)
        return Response({"sha": sha})
    gd, sha = _head(a)
    if sha is None:
        return Response({"sha": None, "files": [], "editable": a.source == "kern"})
    rel = request.query_params.get("path")
    if rel:
        blob = source.read_file(a, gd, sha, rel)
        if blob is None:
            raise ApiError("No such file.", 404)
        binary = b"\0" in blob[:8000]
        return Response({"path": rel, "size": len(blob), "binary": binary,
                         "content": None if binary or len(blob) > source.MAX_FILE else blob.decode("utf-8", errors="replace")})
    return Response({"sha": sha, "files": source.list_files(a, gd, sha), "editable": a.source == "kern"})


@api_view(["GET"])
@handle
def app_data(request, slug):
    """Download APP_DATA_DIR as a .tar.gz (the app's own data is not part of Kern's backups)."""
    a = _app(request, slug)
    d = core.data_dir(a.id)
    if request.query_params.get("download") != "1":
        size = files = 0
        for root, _dirs, names in os.walk(d):
            for n in names:
                files += 1
                try:
                    size += os.lstat(os.path.join(root, n)).st_size
                except OSError:
                    pass
        return Response({"size": size, "files": files})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if d.is_dir():
            tar.add(d, arcname="data")
    buf.seek(0)
    resp = FileResponse(buf, as_attachment=True, filename=f"{a.slug}-data-{timezone.now():%Y%m%d}.tar.gz",
                        content_type="application/gzip")
    return resp


# --------------------------------------------------------------------- builder


def chat_json(c: BuilderChat | None) -> dict:
    if c is None:
        return {"transcript": [], "status": "idle", "progress": [], "pending": ""}
    return {"transcript": c.transcript, "status": c.status, "progress": c.progress, "pending": c.pending,
            "updated": _iso(c.updated)}


def _builder_send(a: App, text: str, user) -> BuilderChat:
    from notes import ai

    with tenancy.use(a.owner):
        if not ai.public_config(a.slug)["configured"]:
            raise ApiError("The AI assistant is not set up yet. Choose a provider in Settings → AI.", 409)
    with transaction.atomic():
        c, _ = BuilderChat.objects.get_or_create(app=a)
        if c.status in ("queued", "running"):
            raise ApiError("The builder is still working on your last message.", 409)
        c.pending = text[:20000]
        c.status = "queued"
        c.stop = False
        c.progress = []
        c.transcript = [*c.transcript, {"role": "user", "text": text[:20000], "at": timezone.now().isoformat()}]
        c.save()
    deploy.kick()
    return c


@api_view(["GET", "POST", "DELETE"])
@handle
def builder(request, slug):
    a = _app(request, slug)
    if request.method == "POST":
        text = str(_body(request).get("message") or "").strip()
        if not text:
            raise ApiError("Write a message first.")
        return Response(chat_json(_builder_send(a, text, request.user)))
    c = BuilderChat.objects.filter(app=a).first()
    if request.method == "DELETE":
        if c and c.status in ("queued", "running"):
            raise ApiError("Stop the builder first.", 409)
        BuilderChat.objects.filter(app=a).delete()
        return Response(chat_json(None))
    return Response(chat_json(c))


@api_view(["POST"])
@handle
def builder_stop(request, slug):
    a = _app(request, slug)
    BuilderChat.objects.filter(app=a, status__in=("queued", "running")).update(stop=True)
    BuilderChat.objects.filter(app=a, status="queued").update(status="idle", pending="")
    return Response(chat_json(BuilderChat.objects.filter(app=a).first()))
