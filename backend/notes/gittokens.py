"""Per-repository git access tokens.

A token looks like ``kern_<id>_<secret>``. The id finds the row in the shared accounts table
(which also records the owner's user id and the repository name), so no user's data is scanned;
the secret is 32 random bytes and only its sha256 is stored. A git client sends the token as the
HTTP Basic password (any username)."""
import datetime as dt
import hashlib
import re
import secrets

from django.utils import timezone
from django.utils.crypto import constant_time_compare

from accounts.models import GitToken

TOKEN_RE = re.compile(r"^kern_(?P<id>\d{1,12})_(?P<secret>[A-Za-z0-9_-]{20,128})$")
EXPIRY_DAYS = (30, 90, 365)
MAX_PER_REPO = 50


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def brief(t: GitToken) -> dict:
    return {
        "id": t.id,
        "label": t.label,
        "scope": t.scope,
        "created": t.created.isoformat(timespec="seconds"),
        "expires": t.expires.isoformat(timespec="seconds") if t.expires else None,
        "expired": bool(t.expires and t.expires <= timezone.now()),
        "last_used": t.last_used.isoformat(timespec="seconds") if t.last_used else None,
    }


def list_for(owner: int, repo: str) -> list[dict]:
    return [brief(t) for t in GitToken.objects.filter(owner=owner, repo=repo).order_by("-created")]


def create(owner: int, repo: str, label: str, scope: str, days) -> tuple[GitToken, str]:
    label = (label or "").strip()[:60]
    if not label:
        raise ValueError("Give the token a label.")
    if scope not in ("read", "write"):
        raise ValueError("Scope must be read or write.")
    if days not in (None, "", 0) and int(days) not in EXPIRY_DAYS:
        raise ValueError("Expiry must be never, 30, 90 or 365 days.")
    if GitToken.objects.filter(owner=owner, repo=repo).count() >= MAX_PER_REPO:
        raise ValueError("Too many tokens for this repository; revoke some first.")
    secret = secrets.token_urlsafe(32)
    t = GitToken.objects.create(
        owner=owner, repo=repo, label=label, scope=scope, secret_hash=_hash(secret),
        expires=timezone.now() + dt.timedelta(days=int(days)) if days else None)
    return t, f"kern_{t.id}_{secret}"


def revoke(owner: int, repo: str, token_id: int) -> bool:
    return bool(GitToken.objects.filter(owner=owner, repo=repo, id=token_id).delete()[0])


def revoke_repo(owner: int, repo: str) -> None:
    GitToken.objects.filter(owner=owner, repo=repo).delete()


def parse(password: str):
    """(id, secret) if the string has the token shape, else None."""
    m = TOKEN_RE.match(password or "")
    return (int(m["id"]), m["secret"]) if m else None


def lookup(token_id: int, secret: str, owner: int, repo: str):
    """The token row if the secret is right, it belongs to this exact owner and repository, and it
    has not expired; otherwise None. Marks it used."""
    t = GitToken.objects.filter(id=token_id).first()
    ok = t is not None and constant_time_compare(t.secret_hash, _hash(secret))
    if not ok or t.owner != owner or t.repo != repo:
        return None
    now = timezone.now()
    if t.expires and t.expires <= now:
        return None
    if not t.last_used or now - t.last_used > dt.timedelta(minutes=1):
        GitToken.objects.filter(id=t.id).update(last_used=now)
    return t
