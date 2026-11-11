"""Git hosting: a JSON API for the browser UI (under /api/git) and the git smart-HTTP
protocol for git clients (under /git/<name>.git, outside /api so the X-Kern guard
does not apply — git clients cannot send that header)."""
import base64
import re
import subprocess
import threading

from django.contrib.auth.hashers import check_password, make_password
from django.http import HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import gitrepo as g
from .models import Setting
from .views import bad

AUTH_KEY = "git_auth"  # {"mode": "off" | "push" | "all", "hash": "..."}; never sent to the browser


def _err(e: g.GitError):
    return bad(str(e), e.status)


def _repo(name):
    return g.repo_path(name)


def handle(fn):
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except g.GitError as e:
            return _err(e)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# --------------------------------------------------------------------- API


@api_view(["GET", "POST"])
@handle
def repos(request):
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get("name", "")).strip()
        path = g.create(name, str(data.get("description", "")))
        return Response(g.summary(name, path), status=201)
    return Response(g.list_repos())


@api_view(["GET", "PATCH", "DELETE"])
@handle
def repo_detail(request, name):
    path = _repo(name)
    if request.method == "DELETE":
        g.delete(name)
        return Response(status=204)
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        if "description" in data:
            g.set_description(path, str(data["description"] or ""))
        if data.get("default_branch"):
            b = str(data["default_branch"])
            if b not in [x["name"] for x in g.branches(path)]:
                return bad("No such branch.")
            g.git(path, "symbolic-ref", "HEAD", f"refs/heads/{b}")
    out = g.summary(name, path)
    out["branch_list"] = g.branches(path)
    out["tag_list"] = g.tags(path)
    return Response(out)


@api_view(["GET"])
@handle
def repo_tree(request, name):
    path = _repo(name)
    sha = g.resolve(path, request.query_params.get("ref"))
    if not sha:
        return Response({"sha": None, "entries": [], "readme": None, "last_commit": None})
    sub = g.clean_path(request.query_params.get("path"))
    return Response({
        "sha": sha,
        "path": sub,
        "entries": g.tree(path, sha, sub),
        "readme": g.readme(path, sha, sub),
        "last_commit": g.last_commit(path, sha, sub),
    })


@api_view(["GET"])
@handle
def repo_blob(request, name):
    path = _repo(name)
    sha = g.resolve(path, request.query_params.get("ref"))
    if not sha:
        return bad("Repository is empty.", 404)
    sub = g.clean_path(request.query_params.get("path"))
    out = g.blob(path, sha, sub)
    out["sha"] = sha
    out["last_commit"] = g.last_commit(path, sha, sub)
    return Response(out)


INLINE_IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
                 "webp": "image/webp", "avif": "image/avif", "ico": "image/x-icon", "bmp": "image/bmp"}


def repo_raw(request, name):
    try:
        return _raw(request, name)
    except g.GitError as e:
        return _plain(str(e), e.status)


def _raw(request, name):
    if request.method != "GET":
        return HttpResponse(status=405)
    path = _repo(name)
    sha = g.resolve(path, request.GET.get("ref"))
    if not sha:
        return HttpResponse(status=404)
    sub = g.clean_path(request.GET.get("path"))
    data = g.raw(path, sha, sub)
    from urllib.parse import quote
    # Raster images may be shown inline in the file viewer; everything else (SVG and
    # HTML included, which could run script) is always a download.
    ext = sub.rsplit(".", 1)[-1].lower() if "." in sub else ""
    mime = INLINE_IMAGES.get(ext) if request.GET.get("inline") else None
    r = HttpResponse(data, content_type=mime or "application/octet-stream")
    disp = "inline" if mime else "attachment"
    r["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(sub.rsplit('/', 1)[-1])}"
    r["Content-Security-Policy"] = "default-src 'none'; sandbox"
    r["X-Content-Type-Options"] = "nosniff"
    return r


@api_view(["GET"])
@handle
def repo_commits(request, name):
    path = _repo(name)
    q = request.query_params
    sha = g.resolve(path, q.get("ref"))
    if not sha:
        return Response({"commits": [], "more": False})
    try:
        page = max(0, int(q.get("page", 0)))
        per = max(1, min(100, int(q.get("per", 40))))
    except ValueError:
        return bad("Invalid page.")
    sub = g.clean_path(q.get("path"))
    commits = g.log(path, sha, sub, skip=page * per, limit=per + 1)
    return Response({"commits": commits[:per], "more": len(commits) > per})


@api_view(["GET"])
@handle
def repo_commit(request, name, sha):
    path = _repo(name)
    full = g.resolve(path, sha)
    return Response(g.commit(path, full))


@api_view(["GET"])
@handle
def repo_stats(request, name):
    path = _repo(name)
    sha = g.resolve(path, request.query_params.get("ref"))
    return Response(g.stats(name, path, sha))


@api_view(["GET", "PUT"])
def git_config(request):
    s = Setting.objects.filter(key=AUTH_KEY).first()
    cur = (s.value if s and isinstance(s.value, dict) else None) or {"mode": "off"}
    if request.method == "PUT":
        data = request.data if isinstance(request.data, dict) else {}
        mode = data.get("mode", cur.get("mode", "off"))
        if mode not in ("off", "push", "all"):
            return bad("Mode must be off, push or all.")
        new = {"mode": mode, "hash": cur.get("hash")}
        if data.get("password"):
            pw = str(data["password"])
            if len(pw) < 6:
                return bad("Use at least 6 characters.")
            new["hash"] = make_password(pw)
        if mode != "off" and not new.get("hash"):
            return bad("Set a password first.")
        Setting.objects.update_or_create(key=AUTH_KEY, defaults={"value": new})
        cur = new
    return Response({"mode": cur.get("mode", "off"), "has_password": bool(cur.get("hash"))})


# ------------------------------------------------------- smart HTTP protocol

SERVICES = {"git-upload-pack", "git-receive-pack"}
PROTO_RE = re.compile(r"^(?P<name>[^/]+)\.git/(?P<rest>info/refs|git-upload-pack|git-receive-pack|HEAD)$")


def _auth_ok(request, write: bool) -> bool:
    s = Setting.objects.filter(key=AUTH_KEY).first()
    cfg = s.value if s and isinstance(s.value, dict) else {}
    mode = cfg.get("mode", "off")
    if mode == "off" or (mode == "push" and not write) or not cfg.get("hash"):
        return True
    h = request.META.get("HTTP_AUTHORIZATION", "")
    if not h.lower().startswith("basic "):
        return False
    try:
        _user, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return check_password(pw, cfg["hash"])


def _plain(msg, status, **headers):
    r = HttpResponse(msg + "\n", status=status, content_type="text/plain; charset=utf-8")
    for k, v in headers.items():
        r[k] = v
    r["Cache-Control"] = "no-cache"
    return r


def _body_reader(request):
    """The raw request body as a file-like object.

    Git sends large pushes with chunked transfer encoding and no Content-Length.
    Django then reports an empty body, so read the WSGI input directly (gunicorn
    de-chunks it); otherwise use Django's length-limited stream.
    """
    if request.META.get("CONTENT_LENGTH"):
        return request
    if "chunked" in request.META.get("HTTP_TRANSFER_ENCODING", "").lower():
        return request.environ["wsgi.input"]
    return None


@csrf_exempt
def git_http(request, name, rest):
    """Hand the request to `git http-backend` (CGI) and stream its response back."""
    try:
        path = g.repo_path(name)
    except g.GitError:
        return _plain("Repository not found.", 404)

    service = request.GET.get("service") if rest == "info/refs" else (rest if rest in SERVICES else None)
    if rest == "info/refs" and service not in SERVICES:
        # The "dumb" protocol is not offered; modern git always asks for a service.
        return _plain("Only the smart HTTP protocol is supported.", 403)
    write = service == "git-receive-pack"

    if request.method == "POST":
        if rest not in SERVICES:
            return _plain("Method not allowed.", 405)
        # A non-CORS-safelisted content type means browsers cannot forge this cross-site.
        if request.META.get("CONTENT_TYPE", "") != f"application/x-{rest}-request":
            return _plain("Unsupported content type.", 415)
    elif request.method not in ("GET", "HEAD") or rest in SERVICES:
        return _plain("Method not allowed.", 405)

    if not _auth_ok(request, write):
        return _plain("Authentication required.", 401, **{"WWW-Authenticate": 'Basic realm="Kern git", charset="UTF-8"'})

    cgi_env = g.env({
        "GIT_PROJECT_ROOT": str(g.root().resolve()),
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": f"/{name}.git/{rest}",
        "REQUEST_METHOD": request.method,
        "QUERY_STRING": request.META.get("QUERY_STRING", ""),
        "CONTENT_TYPE": request.META.get("CONTENT_TYPE", ""),
        "REMOTE_ADDR": request.META.get("REMOTE_ADDR", ""),
        "REMOTE_USER": "kern",
        "GIT_HTTP_MAX_REQUEST_BUFFER": str(100 * 1024 * 1024),
    })
    if request.META.get("CONTENT_LENGTH"):
        cgi_env["CONTENT_LENGTH"] = request.META["CONTENT_LENGTH"]
    if request.META.get("HTTP_CONTENT_ENCODING"):
        cgi_env["HTTP_CONTENT_ENCODING"] = request.META["HTTP_CONTENT_ENCODING"]
    if request.META.get("HTTP_GIT_PROTOCOL"):
        cgi_env["GIT_PROTOCOL"] = request.META["HTTP_GIT_PROTOCOL"]

    proc = subprocess.Popen(["git", "http-backend"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=cgi_env)

    def feed():
        try:
            src = _body_reader(request) if request.method == "POST" else None
            while src is not None:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                proc.stdin.write(chunk)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    errs = []
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    threading.Thread(target=lambda: errs.append(proc.stderr.read()), daemon=True).start()

    # CGI response: headers, blank line, body.
    headers = {}
    status = 200
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.rstrip(b"\r\n")
        if not line:
            break
        k, _, v = line.decode("latin-1").partition(":")
        k, v = k.strip(), v.strip()
        if k.lower() == "status":
            try:
                status = int(v.split()[0])
            except (ValueError, IndexError):
                status = 500
        else:
            headers[k] = v

    def body():
        try:
            while True:
                chunk = proc.stdout.read1(64 * 1024) if hasattr(proc.stdout, "read1") else proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            writer.join(timeout=5)
            proc.stdout.close()
            rc = proc.wait()
            if write and rc == 0 and request.method == "POST":
                try:
                    g.fix_head(path)
                    g.write_meta(path, last_push=g.now_iso())
                    (path / g.STATS_FILE).unlink(missing_ok=True)
                except (OSError, g.GitError):
                    pass

    resp = StreamingHttpResponse(body(), status=status,
                                 content_type=headers.pop("Content-Type", "application/octet-stream"))
    for k, v in headers.items():
        if k.lower() not in ("content-length", "transfer-encoding", "connection"):
            resp[k] = v
    resp["X-Accel-Buffering"] = "no"
    return resp


def git_entry(request, subpath):
    m = PROTO_RE.match(subpath)
    if not m:
        return _plain("Not found.", 404)
    return git_http(request, m.group("name"), m.group("rest"))


git_entry = csrf_exempt(git_entry)
