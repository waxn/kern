"""JSON API for push mirrors and webhooks of a hosted repository (under /api/git/repos/<name>/).

Secrets (mirror token, webhook signing secret) are write-only: send ``secret`` to set it,
``clear_secret: true`` to remove it; responses only say ``has_secret``."""
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from kern import secretbox

from . import gitmirrors, gitwebhooks, remote_guard
from . import gitrepo as g
from .models_git_hooks import GitMirror, GitWebhook, GitWebhookDelivery
from .views import bad
from .views_git import handle

MAX_PER_REPO = 20


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _iso(dt):
    return dt.isoformat() if dt else None


def _guard(fn):
    """Turn address-check failures into 400s."""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except remote_guard.RemoteNotAllowed as e:
            return bad(str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


def _secret_update(obj, data):
    if data.get("clear_secret"):
        obj.secret_enc = ""
    if "secret" in data and str(data["secret"] or ""):
        s = str(data["secret"])
        if len(s) > 500:
            raise g.GitError("That secret is too long.")
        obj.secret_enc = secretbox.encrypt(s)


# ------------------------------------------------------------------ mirrors


def mirror_json(m: GitMirror) -> dict:
    return {"id": m.id, "url": m.url, "username": m.username, "has_secret": bool(m.secret_enc),
            "enabled": m.enabled, "only_protected": m.only_protected, "branch_filter": m.branch_filter,
            "last_attempt": _iso(m.last_attempt), "last_success": _iso(m.last_success),
            "last_error": m.last_error, "syncing": gitmirrors.is_syncing(m.id), "created": _iso(m.created_at)}


def _mirror(name, mid) -> GitMirror:
    g.repo_path(name)
    return get_object_or_404(GitMirror, id=mid, repo=name)


def _fill_mirror(m: GitMirror, data: dict, creating: bool):
    if creating or "url" in data:
        m.url = remote_guard.check_url(str(data.get("url", "")), http="local")["url"]
    if "username" in data:
        m.username = str(data["username"] or "").strip()[:200]
    if m.username and any(c in m.username for c in ":\r\n\0"):
        raise g.GitError("The username can't contain a colon or line breaks.")
    _secret_update(m, data)
    for f in ("enabled", "only_protected"):
        if f in data:
            setattr(m, f, bool(data[f]))
    if "branch_filter" in data:
        m.branch_filter = gitmirrors.clean_filter(data["branch_filter"])


@api_view(["GET", "POST"])
@handle
@_guard
def mirrors(request, name):
    g.repo_path(name)
    if request.method == "POST":
        if GitMirror.objects.filter(repo=name).count() >= MAX_PER_REPO:
            return bad(f"At most {MAX_PER_REPO} mirrors per repository.")
        m = GitMirror(repo=name)
        _fill_mirror(m, _data(request), True)
        m.save()
        if m.enabled:
            gitmirrors.request_sync(m.id, block=_blocking())
            m.refresh_from_db()
        return Response(mirror_json(m), status=201)
    return Response({"mirrors": [mirror_json(m) for m in GitMirror.objects.filter(repo=name)],
                     "local_allowed": remote_guard.local_allowed()})


def _blocking() -> bool:
    from kern import tenancy
    return tenancy.testing()


@api_view(["PATCH", "DELETE"])
@handle
@_guard
def mirror_detail(request, name, mid):
    m = _mirror(name, mid)
    if request.method == "DELETE":
        m.delete()
        return Response(status=204)
    _fill_mirror(m, _data(request), False)
    m.save()
    return Response(mirror_json(m))


@api_view(["POST"])
@handle
def mirror_sync(request, name, mid):
    m = _mirror(name, mid)
    if not m.enabled:
        return bad("This mirror is turned off.")
    state = gitmirrors.request_sync(m.id, block=_blocking())
    m.refresh_from_db()
    return Response({"state": state, **mirror_json(m)}, status=202)


# ----------------------------------------------------------------- webhooks


def _last_delivery(h: GitWebhook):
    d = h.deliveries.first()
    if not d:
        return None
    return {"id": d.id, "event": d.event, "status_code": d.status_code, "ok": d.ok, "error": d.error[:300],
            "at": _iso(d.created_at)}


def hook_json(h: GitWebhook) -> dict:
    return {"id": h.id, "url": h.url, "has_secret": bool(h.secret_enc), "events": h.events, "enabled": h.enabled,
            "last_delivery": _last_delivery(h), "created": _iso(h.created_at)}


def delivery_json(d: GitWebhookDelivery, full=False) -> dict:
    out = {"id": d.id, "guid": str(d.guid), "event": d.event, "status_code": d.status_code, "ok": d.ok,
           "attempts": d.attempts, "duration_ms": d.duration_ms, "error": d.error, "at": _iso(d.created_at)}
    if full:
        out |= {"request_headers": d.request_headers, "request_body": d.request_body,
                "response_body": d.response_body}
    return out


def _hook(name, hid) -> GitWebhook:
    g.repo_path(name)
    return get_object_or_404(GitWebhook, id=hid, repo=name)


def _fill_hook(h: GitWebhook, data: dict, creating: bool):
    if creating or "url" in data:
        h.url = remote_guard.check_url(str(data.get("url", "")), http="yes")["url"]
    if creating or "events" in data:
        h.events = gitwebhooks.clean_events(data.get("events", ["push"] if creating else None))
    _secret_update(h, data)
    if "enabled" in data:
        h.enabled = bool(data["enabled"])


@api_view(["GET", "POST"])
@handle
@_guard
def webhooks(request, name):
    g.repo_path(name)
    if request.method == "POST":
        if GitWebhook.objects.filter(repo=name).count() >= MAX_PER_REPO:
            return bad(f"At most {MAX_PER_REPO} webhooks per repository.")
        h = GitWebhook(repo=name)
        _fill_hook(h, _data(request), True)
        h.save()
        return Response(hook_json(h), status=201)
    return Response({"webhooks": [hook_json(h) for h in GitWebhook.objects.filter(repo=name)],
                     "events": gitwebhooks.event_list(), "local_allowed": remote_guard.local_allowed()})


@api_view(["PATCH", "DELETE"])
@handle
@_guard
def webhook_detail(request, name, hid):
    h = _hook(name, hid)
    if request.method == "DELETE":
        h.delete()
        return Response(status=204)
    _fill_hook(h, _data(request), False)
    h.save()
    return Response(hook_json(h))


@api_view(["POST"])
@handle
def webhook_test(request, name, hid):
    h = _hook(name, hid)
    return Response(delivery_json(gitwebhooks.send_test(h), full=True), status=201)


@api_view(["GET"])
@handle
def webhook_deliveries(request, name, hid):
    h = _hook(name, hid)
    return Response({"deliveries": [delivery_json(d) for d in h.deliveries.all()[:gitwebhooks.KEEP_DELIVERIES]]})


@api_view(["GET"])
@handle
def webhook_delivery(request, name, hid, did):
    h = _hook(name, hid)
    return Response(delivery_json(get_object_or_404(GitWebhookDelivery, id=did, hook=h), full=True))


@api_view(["POST"])
@handle
def webhook_redeliver(request, name, hid, did):
    h = _hook(name, hid)
    d = get_object_or_404(GitWebhookDelivery, id=did, hook=h)
    return Response(delivery_json(gitwebhooks.redeliver(d), full=True), status=201)


def forget_repo(name: str) -> None:
    """A repository was deleted: its mirrors, webhooks and delivery log go with it."""
    GitMirror.objects.filter(repo=name).delete()
    GitWebhook.objects.filter(repo=name).delete()
