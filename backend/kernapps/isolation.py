"""Running app code under its own user.

SECURITY: an app (and every package its build installs) is code you did not necessarily read. In
Docker the worker runs as ``kern`` with just the CAP_SETUID, CAP_SETGID, CAP_CHOWN and CAP_KILL capabilities
(entrypoint.sh), and starts each app's builds and process as a user of its own, uid/gid
``APP_UID_BASE + app id``, through ``setpriv`` with every capability dropped and no_new_privs set.
That user can read its own folder (``apps/<id>/home``) and nothing of Kern's: the data folder is
0711 and everything in it except ``apps/`` is closed to other users (:func:`harden_data_dir`).

Without those capabilities (running Kern from a checkout on your own machine) apps run as the same
user as Kern, which the UI and docs call "not isolated".
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

from django.conf import settings

from . import core

log = logging.getLogger("kern.apps")

APP_UID_BASE = int(os.environ.get("KERN_APPS_UID_BASE", "20000"))
CAP_CHOWN, CAP_KILL, CAP_SETGID, CAP_SETUID = 0, 5, 6, 7

_isolated: bool | None = None


def _cap_eff() -> int:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("CapEff:"):
                return int(line.split()[1], 16)
    except (OSError, ValueError):
        pass
    return 0


def isolated() -> bool:
    """True when apps run as their own users (needs setpriv and the four capabilities)."""
    global _isolated
    if _isolated is None:
        if os.environ.get("KERN_APPS_ISOLATION", "auto") == "off":
            _isolated = False
        else:
            caps = _cap_eff()
            need = (1 << CAP_SETUID) | (1 << CAP_SETGID) | (1 << CAP_CHOWN) | (1 << CAP_KILL)
            _isolated = (os.geteuid() == 0 or caps & need == need) and shutil.which("setpriv") is not None
            if os.environ.get("KERN_APPS_ISOLATION") == "require" and not _isolated:
                raise RuntimeError("KERN_APPS_ISOLATION=require, but the worker can't switch users "
                                   "(needs setpriv and CAP_SETUID, CAP_SETGID, CAP_CHOWN, CAP_KILL).")
    return _isolated


def uid_of(app_id: int) -> int:
    return APP_UID_BASE + int(app_id)


def wrap(cmd: list[str], app_id: int) -> list[str]:
    """``cmd`` run as the app's own user (or unchanged when isolation is off)."""
    if not isolated():
        return cmd
    uid = uid_of(app_id)
    # A non-zero uid with empty inheritable and ambient sets and no_new_privs ends up with no capabilities.
    # (--bounding-set would need CAP_SETPCAP, which the worker doesn't have.)
    return ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups",
            "--inh-caps=-all", "--ambient-caps=-all", "--no-new-privs", "--", *cmd]


class IsolationError(Exception):
    pass


def _chown(p: Path, uid: int, gid: int):
    try:
        os.chown(p, uid, gid, follow_symlinks=False)
    except PermissionError:
        raise IsolationError(f"Kern may not hand {p} to the app's user (the apps service needs CAP_CHOWN).")


def prepare(app_id: int) -> None:
    """Create the app's folders with the right owners. Safe to call again."""
    base = core.app_dir(app_id)
    for d in (base, core.logs_dir(app_id)):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o711)
    os.chmod(core.logs_dir(app_id), 0o700)
    home = core.home_dir(app_id)
    home.mkdir(exist_ok=True)
    if isolated():
        uid = uid_of(app_id)
        if home.stat().st_uid != uid:
            # The app owns its home; Kern (the group) may read it, e.g. to serve a static app's files.
            # chmod first: once the app owns it, Kern may no longer change its mode (no CAP_FOWNER).
            # The setgid bit survives the chown.
            os.chmod(home, 0o2750)
            _chown(home, uid, os.getegid())
        r = run_as(app_id, ["mkdir", "-p", str(core.data_dir(app_id)), str(core.releases_dir(app_id)),
                            str(home / ".cache")])
        if r.returncode:
            raise IsolationError("Could not prepare the app's folder as its own user: "
                                 + r.stderr.decode(errors="replace").strip()[:300])
    else:
        for d in (core.data_dir(app_id), core.releases_dir(app_id), home / ".cache"):
            d.mkdir(parents=True, exist_ok=True)


def run_as(app_id: int, cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("env", {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(core.home_dir(app_id)), "LANG": "C.UTF-8"})
    return subprocess.run(wrap(cmd, app_id), **kw)


def remove_tree(app_id: int, path: Path) -> None:
    """Delete files the app's own user wrote (Kern itself may not be allowed to)."""
    if not path.exists():
        return
    if isolated():
        run_as(app_id, ["rm", "-rf", "--one-file-system", str(path)], timeout=600)
    shutil.rmtree(path, ignore_errors=True)


def remove_app(app_id: int) -> None:
    home = core.home_dir(app_id)
    if home.exists() and isolated():
        # Empty the home as its owner, then remove the (now empty) folder as Kern.
        run_as(app_id, ["find", str(home), "-mindepth", "1", "-delete"], timeout=600)
    shutil.rmtree(core.app_dir(app_id), ignore_errors=True)


def harden_data_dir() -> None:
    """Close Kern's own files to other users so app users can't read them (only when isolating)."""
    if not isolated():
        return
    data = Path(settings.DATA_DIR)
    try:
        os.chmod(data, 0o711)
    except OSError:
        log.warning("cannot chmod %s", data)
    apps = core.apps_root()
    for entry in data.iterdir():
        if entry.resolve() == apps.resolve():
            continue
        try:
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            os.chmod(entry, stat.S_IMODE(mode) & ~0o007)
        except OSError:
            log.warning("cannot close %s", entry)
    os.chmod(apps, 0o711)
