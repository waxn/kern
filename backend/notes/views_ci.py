"""CI JSON API under /api/git/repos/<name>/ci/ (see notes/ci.py)."""
import re

from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import ci
from . import gitrepo as g
from .models_ci import Job, Run
from .views import bad
from .views_git import handle

MAX_LOG_CHUNK = 256 * 1024


def _secs(a, b):
    if not a:
        return None
    return max(0.0, ((b or timezone.now()) - a).total_seconds())


def _iso(d):
    return d.isoformat() if d else None


def run_json(r: Run) -> dict:
    return {
        "id": r.id, "repo": r.repo, "ref": r.ref, "branch": r.branch, "tag": r.tag,
        "sha": r.sha, "subject": r.subject, "trigger": r.trigger, "pusher": r.pusher,
        "status": r.status, "error": r.error, "created": _iso(r.created), "started": _iso(r.started),
        "finished": _iso(r.finished), "duration": _secs(r.started, r.finished),
    }


def job_json(j: Job) -> dict:
    return {"name": j.name, "status": j.status, "note": j.note, "exit_code": j.exit_code,
            "started": _iso(j.started), "finished": _iso(j.finished), "duration": _secs(j.started, j.finished)}


def _run(name, rid) -> Run:
    g.repo_path(name)
    r = Run.objects.filter(pk=rid, repo=name).first()
    if r is None:
        raise g.GitError("No such run.", 404)
    return r


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


@api_view(["GET", "POST"])
@handle
def runs(request, name):
    path = g.repo_path(name)
    if request.method == "POST":
        run = ci.start_manual(name, path, str(_body(request).get("ref") or ""), request.user.username)
        return Response(run_json(run), status=201)
    q = request.query_params
    qs = Run.objects.filter(repo=name)
    ref = (q.get("ref") or "").strip()
    if ref:
        qs = qs.filter(ref__in=[ref, f"refs/heads/{ref}", f"refs/tags/{ref}"])
    try:
        page = max(0, int(q.get("page", 0)))
        per = max(1, min(100, int(q.get("per", 30))))
    except ValueError:
        return bad("Invalid page.")
    rows = list(qs.order_by("-id")[page * per: page * per + per + 1])
    return Response({"runs": [run_json(r) for r in rows[:per]], "more": len(rows) > per})


@api_view(["GET"])
@handle
def run_detail(request, name, rid):
    r = _run(name, rid)
    out = run_json(r)
    out["jobs"] = [job_json(j) for j in r.jobs.all()]
    out["artifacts"] = [{"job": a.job, "name": a.name, "size": a.size} for a in ci.run_artifacts(r)]
    return Response(out)


def _decode(chunk: bytes) -> tuple[str, int]:
    """Decode a slice of a log without cutting a UTF-8 character in half; returns (text, bytes used)."""
    for cut in range(len(chunk), max(len(chunk) - 4, -1), -1):
        try:
            return chunk[:cut].decode("utf-8"), cut
        except UnicodeDecodeError:
            continue
    return chunk.decode("utf-8", "replace"), len(chunk)


@api_view(["GET"])
@handle
def job_log(request, name, rid, job):
    r = _run(name, rid)
    row = r.jobs.filter(name=job).first()
    if row is None:
        raise g.GitError("No such job.", 404)
    try:
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        return bad("Invalid offset.")
    p = ci.log_path(r.id, row.name)
    size, data = 0, b""
    try:
        with open(p, "rb") as f:
            size = p.stat().st_size
            f.seek(offset)
            data = f.read(MAX_LOG_CHUNK)
    except OSError:
        pass
    text, used = _decode(data)
    over = row.status not in (Job.PENDING, Job.RUNNING) or r.status in Run.FINISHED
    return Response({"text": text, "offset": offset + used, "size": size, "done": over and offset + used >= size,
                     "status": row.status})


@api_view(["POST"])
@handle
def run_cancel(request, name, rid):
    return Response(run_json(ci.cancel(_run(name, rid))))


@api_view(["POST"])
@handle
def run_rerun(request, name, rid):
    r = _run(name, rid)
    return Response(run_json(ci.start_rerun(r, g.repo_path(name), request.user.username)), status=201)


@api_view(["GET"])
def artifact_download(request, name, rid, job, rel):
    try:
        _run(name, rid)
    except g.GitError as e:
        return HttpResponse(str(e) + "\n", status=e.status, content_type="text/plain; charset=utf-8")
    p = ci.artifact_path(int(rid), job, rel)
    if p is None:
        return HttpResponse("No such artifact.\n", status=404, content_type="text/plain; charset=utf-8")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", p.name) or "artifact"
    r = FileResponse(open(p, "rb"), as_attachment=True, filename=safe, content_type="application/octet-stream")
    r["X-Content-Type-Options"] = "nosniff"
    r["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return r


@api_view(["GET"])
@handle
def secrets(request, name):
    g.repo_path(name)
    return Response({"secrets": ci.secret_names(name)})


@api_view(["PUT", "DELETE"])
@handle
def secret_item(request, name, secret):
    g.repo_path(name)
    if request.method == "DELETE":
        if not ci.delete_secret(name, secret):
            return bad("No such secret.", 404)
        return Response(status=204)
    ci.set_secret(name, secret, _body(request).get("value"))
    return Response({"secrets": ci.secret_names(name)})


@api_view(["GET"])
@handle
def status(request, name):
    g.repo_path(name)
    shas = [s for s in (request.query_params.get("shas") or "").split(",") if s]
    return Response(ci.status_for_shas(name, shas))


@api_view(["GET"])
@handle
def pipeline(request, name):
    """What the pipeline file of a branch or tag says (for the Run button)."""
    path = g.repo_path(name)
    _full, sha = ci.resolve_ref(path, request.query_params.get("ref") or "")
    parsed, error = ci.load_pipeline(path, sha)
    return Response({"found": bool(parsed or error), "error": error or "", "manual": bool(parsed and parsed["on"]["manual"]),
                     "jobs": [j["name"] for j in (parsed["jobs"] if parsed else [])]})
