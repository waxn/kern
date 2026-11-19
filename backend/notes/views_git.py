"""Git hosting: a JSON API for the browser UI (under /api/git) and the git smart-HTTP
protocol for git clients (under /git/<name>.git, outside /api so the X-Kern guard
does not apply — git clients cannot send that header)."""
import base64
import os
import re
import subprocess
import threading

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.http import HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts import site, sshkeys, throttle
from kern import tenancy

from . import gitevents, gitssh
from . import gitrepo as g
from . import gittokens
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
        gittokens.revoke_repo(request.user.id, name)
        from .views_git_hooks import forget_repo
        forget_repo(name)
        from . import ci
        ci.purge_repo(name)  # runs, logs, artifacts and secrets go with the repository
        sshkeys.delete_for_repo(request.user.id, name)
        return Response(status=204)
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        if "public" in data:
            g.write_meta(path, public=bool(data["public"]))
        if "description" in data:
            g.set_description(path, str(data["description"] or ""))
        if data.get("default_branch"):
            b = str(data["default_branch"])
            if b not in [x["name"] for x in g.branches(path)]:
                return bad("No such branch.")
            g.git(path, "symbolic-ref", "HEAD", f"refs/heads/{b}")
        if "protected" in data:
            g.set_protected(path, data["protected"])
    out = g.summary(name, path)
    out["owner"] = request.user.username
    out["branch_list"] = g.branches(path)
    out["tag_list"] = g.tags(path)
    out["protected"] = g.protected(path)
    return Response(out)


@api_view(["GET", "POST"])
@handle
def repo_tokens(request, name):
    _repo(name)
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        try:
            t, secret = gittokens.create(request.user.id, name, str(data.get("label", "")),
                                         str(data.get("scope", "read")), data.get("expires_days"))
        except (ValueError, TypeError) as e:
            return bad(str(e))
        return Response(gittokens.brief(t) | {"token": secret}, status=201)
    return Response(gittokens.list_for(request.user.id, name))


@api_view(["DELETE"])
@handle
def repo_token(request, name, token_id):
    _repo(name)
    if not gittokens.revoke(request.user.id, name, token_id):
        return bad("No such token.", 404)
    return Response(status=204)


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


def repo_archive(request, name):
    """The tree of a branch, tag or commit as a .zip or .tar.gz download, streamed from `git archive`."""
    try:
        if request.method != "GET":
            return HttpResponse(status=405)
        path = _repo(name)
        ref = request.GET.get("ref") or None
        sha = g.resolve(path, ref)
        if not sha:
            return _plain("Repository is empty.", 404)
        fmt = request.GET.get("format", "zip")
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", ref or g.default_branch(path) or sha[:7]).strip("-") or sha[:7]
        prefix = f"{name}-{label}"
        cmd = g.archive_cmd(path, sha, fmt, prefix)
    except g.GitError as e:
        return _plain(str(e), e.status)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=g.env())

    def body():
        try:
            while chunk := proc.stdout.read(64 * 1024):
                yield chunk
        finally:
            proc.stdout.close()
            proc.kill()
            proc.wait()

    r = StreamingHttpResponse(body(), content_type=g.ARCHIVE_FORMATS[fmt][1])
    r["Content-Disposition"] = f'attachment; filename="{prefix}.{fmt}"'
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
    """Git clients sign in with your Kern username and either your account password or a separate
    git password, which you can set here (handy so your account password never sits in a git
    credential helper)."""
    s = Setting.objects.filter(key=AUTH_KEY).first()
    cur = (s.value if s and isinstance(s.value, dict) else None) or {}
    if request.method == "PUT":
        data = request.data if isinstance(request.data, dict) else {}
        if "password" in data:
            pw = str(data["password"] or "")
            if pw and len(pw) < 10:
                return bad("Use at least 10 characters.")
            cur = {"hash": make_password(pw) if pw else None}
            Setting.objects.update_or_create(key=AUTH_KEY, defaults={"value": cur})
    return Response({
        "username": request.user.username,
        "has_password": bool(cur.get("hash")),
        "enabled": site.get_all()["allow_git"],
        "ssh": ssh_config(request),
    })


def ssh_config(request) -> dict:
    """What the UI needs to show ssh:// clone URLs. ``enabled`` is true while the ssh service's
    heartbeat file is fresh (see gitssh.status), so it is off when the service is not running."""
    beat = gitssh.status()
    host = os.environ.get("KERN_SSH_HOST", "").strip()
    if not host:
        host = request.get_host()
        host = host[:host.index("]") + 1] if host.startswith("[") else host.split(":")[0]
    try:
        port = int(os.environ.get("KERN_SSH_PORT", "") or 2222)
    except ValueError:
        port = 2222
    return {"enabled": bool(beat) and site.get_all()["allow_git"], "host": host, "port": port,
            "fingerprint": beat.get("fingerprint") if beat else None}


# ------------------------------------------------------- smart HTTP protocol

SERVICES = {"git-upload-pack", "git-receive-pack"}
# /git/<name>.git/... (sign in as the owner) or /git/<owner>/<name>.git/... (anonymous or token access)
PROTO_RE = re.compile(r"^(?:(?P<owner>[^/]+)/)?(?P<name>[^/]+)\.git/(?P<rest>info/refs|git-upload-pack|git-receive-pack|HEAD)$")


def _creds(request):
    """(username, password) from HTTP Basic, or None."""
    h = request.META.get("HTTP_AUTHORIZATION", "")
    if not h.lower().startswith("basic "):
        return None
    try:
        name, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return None
    return name.strip()[:150], pw


def _basic_user(request):
    """The active user named by HTTP Basic credentials, or None. Their account password or their
    separate git password both work. Failures are rate limited."""
    creds = _creds(request)
    if creds is None:
        return None
    name, pw = creds
    ukey, ikey = f"git:u:{name.lower()}", f"git:ip:{throttle.client_ip(request)}"
    if throttle.locked(ukey) or throttle.locked(ikey):
        return None
    user = User.objects.filter(username__iexact=name).first() if name else None
    ok = False
    if user is not None and user.is_active:
        from accounts import totp

        # With two-factor sign-in on, the account password alone is not enough: git
        # clients can't send a code, so only the separate git password works.
        ok = (not totp.enabled(user)) and user.check_password(pw)
        if not ok:
            with tenancy.use(user.id):
                s = Setting.objects.filter(key=AUTH_KEY).first()
                h2 = s.value.get("hash") if s and isinstance(s.value, dict) else None
            ok = bool(h2) and check_password(pw, h2)
    else:
        check_password(pw, "pbkdf2_sha256$1200000$x$" + "A" * 43 + "=")  # keep timing alike
    if not ok:
        throttle.fail(ukey, 10)
        throttle.fail(ikey, 80)
        return None
    throttle.clear(ukey)
    return user


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


def _challenge():
    return _plain("Authentication required.", 401, **{"WWW-Authenticate": 'Basic realm="Kern git", charset="UTF-8"'})


def _wants_write(request, rest):
    return (request.GET.get("service") if rest == "info/refs" else rest) == "git-receive-pack"


def git_http(request, name, rest):
    """The original form, /git/<name>.git: always signs in as the repository's owner."""
    if not site.get_all()["allow_git"]:
        return _plain("Git hosting is turned off on this server.", 403)
    user = _basic_user(request)
    if user is None:
        return _challenge()
    with tenancy.use(user.id):
        return _git_http(request, name, rest, user.id, user.username, user.username)


def _is_public(owner_id, name):
    with tenancy.use(owner_id):
        try:
            return bool(g.read_meta(g.repo_path(name)).get("public"))
        except g.GitError:
            return False


def git_http_owner(request, owner_name, name, rest):
    """/git/<owner>/<name>.git: the owner signs in with a password, anyone holding one of the
    repository's tokens uses it as the password, and public repositories may be read anonymously.
    Everything runs inside the owner's tenant."""
    if not site.get_all()["allow_git"]:
        return _plain("Git hosting is turned off on this server.", 403)
    owner = User.objects.filter(username__iexact=owner_name[:150], is_active=True).first()
    write = _wants_write(request, rest)
    creds = _creds(request)

    def serve(remote_user, pusher):
        with tenancy.use(owner.id):
            return _git_http(request, name, rest, owner.id, remote_user, pusher)

    if creds is None:
        # Anonymous: only reads of a public repository. Everything else gets the same challenge,
        # whether or not the owner or repository exists.
        if owner and not write and _is_public(owner.id, name):
            return serve(None, None)
        return _challenge()

    tok = gittokens.parse(creds[1])
    if tok is None:
        user = _basic_user(request)
        if user is None:
            return _challenge()
        if owner and user.id == owner.id:
            return serve(user.username, user.username)
        # Someone else's account is no better than anonymous here.
        if owner and not write and _is_public(owner.id, name):
            return serve(None, None)
        return _plain("Repository not found.", 404)

    tid, secret = tok
    tkey, ikey = f"git:t:{tid}", f"git:ip:{throttle.client_ip(request)}"
    if throttle.locked(tkey) or throttle.locked(ikey):
        return _challenge()
    row = gittokens.lookup(tid, secret, owner.id, name) if owner else None
    if row is None:
        throttle.fail(tkey, 10)
        throttle.fail(ikey, 80)
        return _challenge()
    throttle.clear(tkey)
    if write and row.scope != "write":
        return _plain("This access token is read-only; it cannot push. Create a token with write access.", 403)
    label = re.sub(r"[^\w .@-]", "_", row.label)
    return serve(f"token:{label}", f"token:{label}")


def _git_http(request, name, rest, uid, remote_user, pusher):
    """Hand the request to `git http-backend` (CGI) and stream its response back.
    `pusher` names who is pushing (the username, or `token:<label>`)."""
    try:
        path = g.repo_path(name)
    except g.GitError:
        return _plain("Repository not found.", 404)

    service = request.GET.get("service") if rest == "info/refs" else (rest if rest in SERVICES else None)
    if rest == "info/refs" and service not in SERVICES:
        # The "dumb" protocol is not offered; modern git always asks for a service.
        return _plain("Only the smart HTTP protocol is supported.", 403)
    write = service == "git-receive-pack"
    pushing = write and request.method == "POST"
    before = gitevents.snapshot(path) if pushing else None

    if request.method == "POST":
        if rest not in SERVICES:
            return _plain("Method not allowed.", 405)
        # A non-CORS-safelisted content type means browsers cannot forge this cross-site.
        if request.META.get("CONTENT_TYPE", "") != f"application/x-{rest}-request":
            return _plain("Unsupported content type.", 415)
    elif request.method not in ("GET", "HEAD") or rest in SERVICES:
        return _plain("Method not allowed.", 405)

    cgi_env = g.env({
        "GIT_PROJECT_ROOT": str(g.root().resolve()),
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": f"/{name}.git/{rest}",
        "REQUEST_METHOD": request.method,
        "QUERY_STRING": request.META.get("QUERY_STRING", ""),
        "CONTENT_TYPE": request.META.get("CONTENT_TYPE", ""),
        "REMOTE_ADDR": request.META.get("REMOTE_ADDR", ""),
        **({"REMOTE_USER": remote_user} if remote_user else {}),
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
            if pushing and rc == 0:
                with tenancy.use(uid):
                    gitevents.after_push(uid, name, path, before, pusher=pusher, via="http")

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
    if m.group("owner"):
        return git_http_owner(request, m.group("owner"), m.group("name"), m.group("rest"))
    return git_http(request, m.group("name"), m.group("rest"))


git_entry = csrf_exempt(git_entry)
