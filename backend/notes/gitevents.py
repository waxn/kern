"""What happens after a push, whichever way it arrived (smart HTTP, SSH).

Callers snapshot the refs with :func:`snapshot` before running ``git-receive-pack`` and call
:func:`after_push` once it exits successfully. That does Kern's own bookkeeping (HEAD, last push,
stats cache) and then hands the list of changed refs to every registered listener (CI, mirrors,
webhooks…) on a background thread, so a slow listener never holds up the git client.

Register a listener from your own module with ``@gitevents.on_push`` and add the module to
:data:`LISTENER_MODULES` so it is imported before the first push.
"""
import importlib
import logging
from dataclasses import dataclass
from pathlib import Path

from kern import tenancy

from . import gitrepo as g

log = logging.getLogger(__name__)

ZERO = "0" * 40

# Modules that register push listeners; imported lazily on the first push.
LISTENER_MODULES: list[str] = [
    "notes.ci",
    "notes.gitmirrors",
    "notes.gitwebhooks",
]

_listeners = []
_loaded = False


@dataclass(frozen=True)
class RefUpdate:
    ref: str  # full name, e.g. refs/heads/main
    old: str  # ZERO when the ref was created
    new: str  # ZERO when the ref was deleted

    @property
    def created(self) -> bool:
        return self.old == ZERO

    @property
    def deleted(self) -> bool:
        return self.new == ZERO

    @property
    def branch(self) -> str | None:
        return self.ref[len("refs/heads/"):] if self.ref.startswith("refs/heads/") else None

    @property
    def tag(self) -> str | None:
        return self.ref[len("refs/tags/"):] if self.ref.startswith("refs/tags/") else None


@dataclass(frozen=True)
class PushEvent:
    uid: int  # the owner of the repository (whose tenant is active)
    repo: str  # repository name
    path: Path
    updates: tuple[RefUpdate, ...]
    pusher: str  # who pushed: a username, or e.g. "token:ci" / "key:laptop"
    via: str  # "http" or "ssh"


def on_push(fn):
    """Register ``fn(event: PushEvent)``. It runs with the owner's tenant active."""
    _listeners.append(fn)
    return fn


def _load():
    global _loaded
    if not _loaded:
        for m in LISTENER_MODULES:
            importlib.import_module(m)
        _loaded = True


def snapshot(path: Path) -> dict[str, str]:
    """refname → object SHA for every branch and tag."""
    out = {}
    raw = g.text(path, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags", check=False)
    for line in raw.splitlines():
        ref, _, sha = line.partition(" ")
        if ref and sha:
            out[ref] = sha
    return out


def diff(before: dict[str, str], after: dict[str, str]) -> list[RefUpdate]:
    ups = []
    for ref in sorted(set(before) | set(after)):
        old, new = before.get(ref, ZERO), after.get(ref, ZERO)
        if old != new:
            ups.append(RefUpdate(ref, old, new))
    return ups


def after_push(uid: int, name: str, path: Path, before: dict[str, str], pusher: str, via: str,
               background: bool = True) -> list[RefUpdate]:
    """Bookkeeping after a successful receive-pack, then notify listeners. Call with the owner's tenant
    active. Returns the ref updates."""
    try:
        g.fix_head(path)
        g.write_meta(path, last_push=g.now_iso())
        (path / g.STATS_FILE).unlink(missing_ok=True)
    except (OSError, g.GitError):
        log.exception("post-push bookkeeping failed for %s", name)
    try:
        updates = diff(before, snapshot(path))
    except g.GitError:
        updates = []
    if not updates:
        return updates
    _load()
    if not _listeners:
        return updates
    event = PushEvent(uid, name, path, tuple(updates), pusher, via)
    if background and not tenancy.testing():
        tenancy.spawn(_notify, event)
    else:
        with tenancy.use(uid):
            _notify(event)
    return updates


def _notify(event: PushEvent):
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception:  # one broken listener must not stop the others
            log.exception("push listener %s failed for %s", getattr(fn, "__name__", fn), event.repo)
