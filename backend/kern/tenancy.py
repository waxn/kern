"""Per-user storage.

Every user owns a private folder, ``DATA_DIR/users/<id>/``, holding their own SQLite database,
uploaded files, git repositories and backups. Accounts, sessions and site settings live in the
shared ``default`` database. Because the notes tables only exist inside a user's own database,
a request can only ever read or write the data of the user it was authenticated as: there is no
"owner" column to forget to filter on.

The active user is tracked in a context variable that the access middleware sets for each
request (and ``spawn``/``use`` carry into background work). With no active user, touching the
notes models fails closed.
"""
import contextvars
import copy
import threading
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections, transaction

_uid = contextvars.ContextVar("kern_uid", default=None)
_lock = threading.RLock()
_ready: set[str] = set()


class NoTenant(RuntimeError):
    """Raised when per-user data is touched with no user active."""


def testing() -> bool:
    return bool(getattr(settings, "KERN_TESTING", False))


def alias_of(uid: int) -> str:
    return "default" if testing() else f"u{int(uid)}"


def users_root() -> Path:
    return Path(settings.DATA_DIR) / "users"


def user_dir(uid: int) -> Path:
    return users_root() / str(int(uid))


def current_uid():
    return _uid.get()


def current_alias() -> str:
    uid = _uid.get()
    if uid is not None:
        return alias_of(uid)
    if testing():
        return "default"
    raise NoTenant("No user is active for this request.")


def conn():
    return connections[current_alias()]


def atomic():
    return transaction.atomic(using=current_alias())


def _base() -> Path:
    uid = _uid.get()
    if testing() or uid is None:
        if testing():
            return Path(settings.DATA_DIR)
        raise NoTenant("No user is active for this request.")
    return user_dir(uid)


def data_dir() -> Path:
    return _base()


def media_root() -> Path:
    if testing():
        return Path(settings.MEDIA_ROOT)
    p = _base() / "media"
    p.mkdir(parents=True, exist_ok=True)
    return p


def git_root() -> Path:
    if testing():
        return Path(getattr(settings, "KERN_GIT_ROOT", None) or Path(settings.DATA_DIR) / "git")
    return _base() / "git"


def backup_dir() -> Path:
    return _base() / "backups"


def db_path() -> str:
    return str(conn().settings_dict["NAME"])


def ensure_db(uid: int) -> str:
    """Register the user's database with Django, creating and migrating it the first time."""
    alias = alias_of(uid)
    if alias == "default" or alias in _ready:
        return alias
    with _lock:
        if alias in _ready:
            return alias
        d = user_dir(uid)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        (d / "media").mkdir(exist_ok=True)
        if alias not in connections.settings:
            cfg = copy.deepcopy(connections.settings["default"])
            cfg["NAME"] = d / "kern.sqlite3"
            connections.settings[alias] = cfg
        call_command("migrate", "notes", database=alias, interactive=False, verbosity=0)
        _ready.add(alias)
    return alias


def forget_db(uid: int) -> None:
    alias = alias_of(uid)
    if alias == "default":  # tests share the default database; never unregister it
        return
    with _lock:
        try:
            connections[alias].close()
        except Exception:
            pass
        connections.settings.pop(alias, None)
        try:
            del connections[alias]
        except Exception:
            pass
        _ready.discard(alias)


@contextmanager
def use(uid: int):
    """Run the block as this user (their database, files and repositories)."""
    ensure_db(uid)
    token = _uid.set(int(uid))
    try:
        yield
    finally:
        _uid.reset(token)


def spawn(target, *args, **kwargs) -> threading.Thread:
    """Start a daemon thread that acts for the current user."""
    uid = _uid.get()

    def run():
        if uid is None:
            return target(*args, **kwargs)
        with use(uid):
            return target(*args, **kwargs)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def close_connections() -> None:
    connections.close_all()
