"""Webhooks: tell another service when something happens in a hosted repository.

Other features send their own events with :func:`emit`::

    from notes import gitwebhooks
    gitwebhooks.register_event("release", "Release published")      # once, at import time
    gitwebhooks.emit(owner_uid, "myrepo", "release", {"tag": "v1.0"})  # when it happens

``emit(owner_uid, repo, event, payload)`` finds the repository's enabled webhooks subscribed to
``event`` and delivers to each on its own thread (synchronously under KERN_TESTING). ``payload``
is a dict (or a zero-argument function returning one, called only if a hook is subscribed); Kern
adds ``event``, ``repository`` ({name, owner}) and ``timestamp``. It returns how many hooks were
notified and never raises.

A delivery is a POST of the JSON body with ``Content-Type: application/json``,
``User-Agent: Kern-Hookshot``, ``X-Kern-Event``, ``X-Kern-Delivery`` (a UUID) and, when the hook has a
secret, ``X-Kern-Signature-256: sha256=<hex HMAC-SHA256 of the body>``. 10 second timeout,
redirects are not followed, network errors and 5xx answers are retried twice with backoff, and
the last 30 deliveries per hook are kept. See docs/git-mirrors-webhooks.md.

SECURITY: URLs go through :mod:`notes.remote_guard` when saved and again before each attempt
(webhooks resolve DNS themselves, so a name that changes between the check and the connection is
a small remaining window); secrets are encrypted with ``kern.secretbox`` and never returned.
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import requests
from django.contrib.auth.models import User

from kern import secretbox, tenancy

from . import gitevents
from . import gitrepo as g
from . import remote_guard
from .models_git_hooks import GitWebhook, GitWebhookDelivery

log = logging.getLogger(__name__)

TIMEOUT = 10  # seconds per attempt
BACKOFF = (1.0, 4.0)  # waits before the 2nd and 3rd attempt
KEEP_DELIVERIES = 30
MAX_RESPONSE = 4000  # characters of the response body kept
MAX_REFS = 50  # ref updates per push payload
MAX_COMMITS = 20  # commits per ref update
USER_AGENT = "Kern-Hookshot"

# name -> label. Features add their own with register_event(); "ping" is only ever sent by "Send test".
EVENTS: dict[str, str] = {"push": "Push"}


def register_event(name: str, label: str) -> None:
    EVENTS[name] = label


def event_list() -> list[dict]:
    return [{"name": k, "label": v} for k, v in EVENTS.items()]


def clean_events(value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise g.GitError("Choose at least one event.")
    out = []
    for e in value:
        if e not in EVENTS:
            raise g.GitError(f"Unknown event “{str(e)[:40]}”.")
        if e not in out:
            out.append(e)
    return out


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ payloads


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def envelope(owner_uid: int, repo: str, event: str, payload: dict) -> dict:
    owner = User.objects.filter(id=owner_uid).values_list("username", flat=True).first() or ""
    return {"event": event, "repository": {"name": repo, "owner": owner}, "timestamp": _now(), **payload}


def commits_of(path, update: gitevents.RefUpdate) -> list[dict]:
    """Up to MAX_COMMITS commits a ref update brought in (``git log old..new``)."""
    if update.deleted:
        return []
    if update.created:
        # Only what no other branch or tag already had.
        short = update.ref.split("/", 2)[2]  # --exclude patterns are relative to refs/heads or refs/tags
        args = [update.new, "--not", f"--exclude={short}", "--branches", f"--exclude={short}", "--tags"]
    else:
        args = [f"{update.old}..{update.new}"]
    raw = g.text(path, "log", f"--max-count={MAX_COMMITS}", "--format=%H%x1f%an%x1f%aI%x1f%s", *args, "--", check=False)
    out = []
    for line in raw.splitlines():
        sha, _, rest = line.partition("\x1f")
        author, _, rest = rest.partition("\x1f")
        date, _, subject = rest.partition("\x1f")
        if g.SHA_RE.match(sha):
            out.append({"sha": sha, "subject": subject[:200], "author": author, "date": date})
    return out


def push_payload(event: gitevents.PushEvent) -> dict:
    ups = []
    for u in event.updates[:MAX_REFS]:
        ups.append({"ref": u.ref, "before": u.old, "after": u.new, "created": u.created, "deleted": u.deleted,
                    "commits": commits_of(event.path, u)})
    out = {"pusher": event.pusher, "via": event.via, "refs": ups}
    if len(event.updates) > MAX_REFS:
        out["refs_truncated"] = len(event.updates) - MAX_REFS
    return out


# ------------------------------------------------------------------ delivery


def _post(url: str, body: bytes, headers: dict) -> tuple[int, str]:
    """One HTTP attempt: (status, start of the response body). Raises requests exceptions."""
    with requests.Session() as s:
        s.trust_env = False  # no proxy settings from the environment
        r = s.post(url, data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False, stream=True)
        try:
            chunk = r.raw.read(MAX_RESPONSE * 4, decode_content=True) or b""
        finally:
            r.close()
        return r.status_code, chunk.decode(r.encoding or "utf-8", errors="replace")[:MAX_RESPONSE]


def _attempts(hook: GitWebhook, headers: dict, body: bytes) -> dict:
    result = {"status_code": None, "ok": False, "error": "", "response_body": "", "attempts": 0}
    started = time.monotonic()
    for i in range(len(BACKOFF) + 1):
        if i:
            time.sleep(BACKOFF[i - 1])
        result["attempts"] = i + 1
        try:
            remote_guard.check_url(hook.url, http="yes")
        except remote_guard.RemoteNotAllowed as e:
            result["error"] = str(e)
            break
        try:
            code, text = _post(hook.url, body, headers)
        except requests.RequestException as e:
            result.update(status_code=None, error=f"{type(e).__name__}: {str(e)[:300]}", response_body="")
            continue
        result.update(status_code=code, response_body=text, error="")
        if 200 <= code < 300:
            result["ok"] = True
        elif 300 <= code < 400:
            result["error"] = "Redirects are not followed."
        elif code >= 500:
            result["error"] = f"The server answered {code}."
            continue
        else:
            result["error"] = f"The server answered {code}."
        break
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def deliver(hook: GitWebhook, event: str, body: bytes, guid: uuid.UUID | None = None) -> GitWebhookDelivery:
    """Send ``body`` to the hook and record the outcome in its delivery log."""
    guid = guid or uuid.uuid4()
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "X-Kern-Event": event,
               "X-Kern-Delivery": str(guid)}
    try:
        secret = secretbox.decrypt(hook.secret_enc) if hook.secret_enc else ""
    except secretbox.SecretBoxError:
        secret = None
    if secret:
        headers["X-Kern-Signature-256"] = sign(secret, body)
    if secret is None:
        res = {"status_code": None, "ok": False, "attempts": 0, "duration_ms": 0, "response_body": "",
               "error": "The stored secret couldn't be decrypted. Enter it again."}
    else:
        res = _attempts(hook, headers, body)
    d = GitWebhookDelivery.objects.create(hook=hook, guid=guid, event=event, request_headers=headers,
                                          request_body=body.decode("utf-8", errors="replace"), **res)
    old = list(GitWebhookDelivery.objects.filter(hook=hook).order_by("-id").values_list("id", flat=True)[KEEP_DELIVERIES:])
    if old:
        GitWebhookDelivery.objects.filter(id__in=old).delete()
    return d


def _deliver_by_id(hook_id: int, event: str, body: bytes) -> None:
    try:
        hook = GitWebhook.objects.filter(id=hook_id, enabled=True).first()
        if hook:
            deliver(hook, event, body)
    except Exception:
        log.exception("webhook %s delivery crashed", hook_id)
    finally:
        if not tenancy.testing():
            tenancy.close_connections()


def encode(data: dict) -> bytes:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()


def emit(owner_uid: int, repo: str, event: str, payload) -> int:
    """Deliver ``event`` to the repository's subscribed webhooks. See the module docstring."""
    try:
        with tenancy.use(owner_uid):
            hooks = [h for h in GitWebhook.objects.filter(repo=repo, enabled=True) if event in (h.events or [])]
            if not hooks:
                return 0
            data = payload() if callable(payload) else payload
            body = encode(envelope(owner_uid, repo, event, dict(data or {})))
            for h in hooks:
                if tenancy.testing():
                    _deliver_by_id(h.id, event, body)
                else:
                    tenancy.spawn(_deliver_by_id, h.id, event, body)
            return len(hooks)
    except Exception:
        log.exception("emit %s for %s failed", event, repo)
        return 0


def send_test(hook: GitWebhook) -> GitWebhookDelivery:
    owner = tenancy.current_uid()
    data = envelope(owner, hook.repo, "ping", {"zen": "Kern says hello.", "hook_id": hook.id})
    return deliver(hook, "ping", encode(data))


def redeliver(d: GitWebhookDelivery) -> GitWebhookDelivery:
    return deliver(d.hook, d.event, d.request_body.encode())


@gitevents.on_push
def _on_push(event):
    emit(event.uid, event.repo, "push", lambda: push_payload(event))
