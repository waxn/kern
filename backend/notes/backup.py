"""Full workspace backups and restore.

A backup holds everything in the data folder that matters: the database (pages, settings,
bookmarks with their saved pages, the AI key), uploaded files and their versions, and the git
repositories. Downloaded videos are optional ("backup_downloads" in the "data" setting), since
they are large and can be downloaded again. Not included: the backups themselves and the
secret key (a new one is made when missing).
"""
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile

from django.conf import settings
from django.core.management import call_command
from kern import tenancy
from django.utils import timezone

NAME_RE = re.compile(r"^kern-\d{8}-\d{6}(?:-\d+)?(?:-[a-z]+)?\.zip$")
_locks: dict = {}


def _bdir():
    return globals().get("BACKUP_DIR") or tenancy.backup_dir()  # BACKUP_DIR: tests point it elsewhere


def __getattr__(name):  # backup.BACKUP_DIR: the active user's backup folder
    if name == "BACKUP_DIR":
        return _bdir()
    raise AttributeError(name)


class _UserLock:
    """One backup/restore at a time per user."""

    def _l(self):
        return _locks.setdefault(tenancy.current_uid(), threading.Lock())

    def __enter__(self):
        self._l().acquire()

    def __exit__(self, *a):
        self._l().release()

    def locked(self):
        return self._l().locked()


_lock = _UserLock()


def _db_path():
    return tenancy.db_path()


DOWNLOADS = "web"  # media/web/<bookmark>/: videos downloaded for bookmarks


def _data_settings() -> dict:
    from .models import Setting
    cfg = Setting.objects.filter(key="data").values_list("value", flat=True).first() or {}
    return cfg if isinstance(cfg, dict) else {}


def include_downloads_default() -> bool:
    return bool(_data_settings().get("backup_downloads", False))


def _git_root():
    from .gitrepo import root
    return root()


def _walk(base):
    """Files under base as (full path, path relative to base with forward slashes)."""
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            full = os.path.join(dirpath, f)
            yield full, os.path.relpath(full, base).replace(os.sep, "/")


def _size(path) -> int:
    total = 0
    for full, _rel in _walk(path):
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return total


def _latest_migration() -> str:
    from django.db.migrations.recorder import MigrationRecorder
    names = [n for (a, n) in MigrationRecorder(tenancy.conn()).applied_migrations() if a == "notes"]
    return max(names) if names else ""


def create(kind: str = "manual", downloads: bool | None = None) -> dict:
    """Write kern-YYYYmmdd-HHMMSS[-kind].zip: a consistent copy of the database, all files and
    the git repositories, plus downloaded videos when asked (default: the backup setting)."""
    if downloads is None:
        downloads = include_downloads_default()
    with _lock:
        _bdir().mkdir(parents=True, exist_ok=True)
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        suffix = "" if kind == "manual" else "-" + kind
        name = f"kern-{stamp}{suffix}.zip"
        n = 1
        while (_bdir() / name).exists():  # several backups within one second
            n += 1
            name = f"kern-{stamp}-{n}{suffix}.zip"
        path = _bdir() / name
        tmpdir = tempfile.mkdtemp(dir=tenancy.data_dir())
        try:
            snap = os.path.join(tmpdir, "kern.sqlite3")
            tenancy.conn().ensure_connection()
            dst = sqlite3.connect(snap)
            with dst:
                tenancy.conn().connection.backup(dst)  # consistent even while the app is writing
            dst.close()
            from .models import Attachment, Card, Document
            from .models_web import WebArchive
            git = _git_root()
            repos = sorted(d for d in os.listdir(git) if d.endswith(".git") and os.path.isdir(git / d))
            manifest = {
                "app": "kern", "format": 2, "created_at": timezone.now().isoformat(), "kind": kind,
                "migration": _latest_migration(),
                "contents": {"database": True, "files": True, "git": True, "downloads": bool(downloads)},
                "counts": {"documents": Document.objects.count(), "cards": Card.objects.count(),
                           "files": Attachment.objects.count(), "bookmarks": WebArchive.objects.count(),
                           "repositories": len(repos)},
            }
            partial = str(path) + ".part"
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, "kern.sqlite3")
                for full, rel in _walk(tenancy.media_root()):
                    if not downloads and rel.startswith(DOWNLOADS + "/"):
                        continue
                    # Videos are already compressed: store them as they are (much faster).
                    big = rel.startswith(DOWNLOADS + "/")
                    z.write(full, "media/" + rel, compress_type=zipfile.ZIP_STORED if big else zipfile.ZIP_DEFLATED)
                for repo in repos:
                    # Directory entries too: git needs its (often empty) refs/ and objects/ folders.
                    for dirpath, _dirs, _files in os.walk(git / repo):
                        rel = os.path.relpath(dirpath, git / repo).replace(os.sep, "/")
                        z.writestr(f"git/{repo}/" + ("" if rel == "." else rel + "/"), b"")
                    for full, rel in _walk(git / repo):
                        if rel.endswith(".lock"):  # a push in progress; its result is not final yet
                            continue
                        z.write(full, f"git/{repo}/{rel}")
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
            os.replace(partial, path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        prune()
        return info(path)


def contents_of(manifest: dict) -> dict:
    """What a backup holds. Backups from before format 2 had the database and all files (videos
    included, as they lived under media/) but no git repositories."""
    if manifest.get("format", 1) >= 2:
        return {"database": True, "files": True, "git": False, "downloads": False, **(manifest.get("contents") or {})}
    return {"database": True, "files": True, "git": False, "downloads": True}


def info(path) -> dict:
    st = os.stat(path)
    kind = "manual"
    m = re.search(r"-([a-z]+)\.zip$", os.path.basename(path))
    if m:
        kind = m.group(1)
    contents = None
    try:
        with zipfile.ZipFile(path) as z:
            contents = contents_of(json.loads(z.read("manifest.json")))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        pass
    return {"name": os.path.basename(path), "size": st.st_size,
            "created_at": dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(), "kind": kind,
            "contents": contents}


def list_backups() -> list[dict]:
    if not _bdir().exists():
        return []
    items = [info(_bdir() / n) for n in os.listdir(_bdir()) if NAME_RE.match(n)]
    # Newest first, by file time (names alone misorder several backups made in one second).
    return sorted(items, key=lambda i: (os.stat(_bdir() / i["name"]).st_mtime_ns, i["name"]), reverse=True)


def path_for(name: str):
    if not NAME_RE.match(name or ""):
        raise FileNotFoundError(name)
    p = _bdir() / name
    if not p.exists():
        raise FileNotFoundError(name)
    return p


def prune(keep_auto: int = 7, keep_safety: int = 3) -> None:
    items = list_backups()
    for kind, keep in (("auto", keep_auto), ("prerestore", keep_safety)):
        for i in [x for x in items if x["kind"] == kind][keep:]:
            os.remove(_bdir() / i["name"])


def validate(zip_path) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        if "manifest.json" not in names or "kern.sqlite3" not in names:
            raise ValueError("This is not a Kern backup (manifest.json or kern.sqlite3 is missing).")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "kern":
            raise ValueError("This is not a Kern backup.")
        for n in names:
            if n.startswith("/") or ".." in n.split("/"):
                raise ValueError("The backup contains unsafe file paths.")
    return manifest


def restore(zip_path) -> dict:
    """Replace the whole workspace with a backup. A safety backup is taken first."""
    manifest = validate(zip_path)
    contents = contents_of(manifest)
    # The safety copy holds whatever the restore replaces (videos too, if the backup brings its own).
    safety = create("prerestore", downloads=contents["downloads"])
    git = _git_root()
    with _lock:
        tmpdir = tempfile.mkdtemp(dir=tenancy.data_dir())
        git_tmp = tempfile.mkdtemp(dir=git.parent, prefix=".git-restore-") if contents["git"] else None
        try:
            def extract(z, prefix, dest):
                os.makedirs(dest, exist_ok=True)
                for n in z.namelist():
                    if n.startswith(prefix) and n.endswith("/"):
                        os.makedirs(os.path.join(dest, n[len(prefix):]), exist_ok=True)
                    elif n.startswith(prefix):
                        target = os.path.join(dest, n[len(prefix):])
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with z.open(n) as src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)

            with zipfile.ZipFile(zip_path) as z:
                z.extract("kern.sqlite3", tmpdir)
                media_tmp = os.path.join(tmpdir, "media")
                extract(z, "media/", media_tmp)
                if git_tmp:
                    extract(z, "git/", git_tmp)
            db_file = os.path.join(tmpdir, "kern.sqlite3")
            check = sqlite3.connect(db_file)
            ok = check.execute("PRAGMA integrity_check").fetchone()[0]
            has = check.execute("SELECT count(*) FROM sqlite_master WHERE name='notes_document'").fetchone()[0]
            if ok != "ok" or not has:
                check.close()
                raise ValueError("The database in this backup is damaged.")
            # Copy pages into the live database in place: other connections stay valid.
            tenancy.conn().ensure_connection()
            live = tenancy.conn().connection
            check.backup(live)
            check.close()
            tenancy.conn().close()
            media = str(tenancy.media_root())
            current_downloads = os.path.join(media, DOWNLOADS)
            if not contents["downloads"] and os.path.isdir(current_downloads):
                # The backup has no videos: keep the ones on disk rather than lose them.
                shutil.rmtree(os.path.join(media_tmp, DOWNLOADS), ignore_errors=True)
                shutil.move(current_downloads, os.path.join(media_tmp, DOWNLOADS))
            _swap(media_tmp, media)
            if git_tmp:
                _swap(git_tmp, str(git))
                git_tmp = None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            if git_tmp:
                shutil.rmtree(git_tmp, ignore_errors=True)
    call_command("migrate", "notes", database=tenancy.current_alias(), interactive=False, verbosity=0)  # backups from older versions
    _forget_missing_videos()
    return {"restored": manifest, "contents": contents, "safety_backup": safety["name"]}


def _swap(new: str, live: str) -> None:
    """Put the folder new in place of live (moving the old one aside until it succeeds)."""
    old = live.rstrip("/") + ".before-restore"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(live):
        os.replace(live, old)
    shutil.move(new, live)
    shutil.rmtree(old, ignore_errors=True)


def _forget_missing_videos() -> None:
    """Bookmarks whose downloaded video is not on disk go back to "not downloaded"."""
    from .models_web import WebArchive
    for a in WebArchive.objects.exclude(video_path=""):
        if not os.path.isfile(os.path.join(tenancy.media_root(), a.video_path)):
            a.video_path = ""
            a.video_status = ""
            a.save(update_fields=["video_path", "video_status"])


def maybe_auto_backup() -> None:
    """Daily automatic backup, started in the background when the app is used."""
    if _data_settings().get("auto_backup") is False:
        return
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    if autos and timezone.now() - dt.datetime.fromisoformat(autos[0]["created_at"]) < dt.timedelta(hours=24):
        return
    if _lock.locked():
        return

    def run():
        try:
            create("auto")
        except Exception:  # never break the request that triggered it
            pass
        finally:
            tenancy.close_connections()

    tenancy.spawn(run)


def storage() -> dict:
    size = _size
    db = _db_path()
    db_size = sum(os.path.getsize(p) for p in (db, db + "-wal") if os.path.exists(p))
    from .models import Attachment, Block, Card, Database, Document, DocVersion, Task
    return {
        "database_bytes": db_size,
        "media_bytes": size(tenancy.media_root()),
        "downloads_bytes": size(os.path.join(tenancy.media_root(), DOWNLOADS)),
        "git_bytes": size(_git_root()),
        "backups_bytes": size(_bdir()) if _bdir().exists() else 0,
        "counts": {
            "pages": Document.objects.filter(entry_of__isnull=True, trashed_at__isnull=True).count(),
            "entries": Document.objects.filter(entry_of__isnull=False, trashed_at__isnull=True).count(),
            "databases": Database.objects.count(), "blocks": Block.objects.count(),
            "cards": Card.objects.count(), "tasks": Task.objects.count(), "files": Attachment.objects.count(),
            "versions": DocVersion.objects.count(),
            "trashed": Document.objects.filter(trashed_at__isnull=False).count(),
        },
        "data_dir": str(tenancy.data_dir()),
    }
