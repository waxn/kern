"""Full workspace backups (database + uploaded files) and restore."""
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
from django.db import connection
from django.utils import timezone

BACKUP_DIR = settings.DATA_DIR / "backups"
NAME_RE = re.compile(r"^kern-\d{8}-\d{6}(?:-[a-z]+)?\.zip$")
_lock = threading.Lock()


def _db_path():
    return str(settings.DATABASES["default"]["NAME"])


def _latest_migration() -> str:
    from django.db.migrations.recorder import MigrationRecorder
    row = MigrationRecorder.Migration.objects.filter(app="notes").order_by("-id").first()
    return row.name if row else ""


def create(kind: str = "manual") -> dict:
    """Write kern-YYYYmmdd-HHMMSS[-kind].zip with a consistent copy of the database and all media."""
    with _lock:
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        name = f"kern-{stamp}{'' if kind == 'manual' else '-' + kind}.zip"
        path = BACKUP_DIR / name
        tmpdir = tempfile.mkdtemp(dir=settings.DATA_DIR)
        try:
            snap = os.path.join(tmpdir, "kern.sqlite3")
            connection.ensure_connection()
            dst = sqlite3.connect(snap)
            with dst:
                connection.connection.backup(dst)  # consistent even while the app is writing
            dst.close()
            from .models import Attachment, Card, Document
            manifest = {
                "app": "kern", "format": 1, "created_at": timezone.now().isoformat(), "kind": kind,
                "migration": _latest_migration(),
                "counts": {"documents": Document.objects.count(), "cards": Card.objects.count(),
                           "files": Attachment.objects.count()},
            }
            partial = str(path) + ".part"
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
                z.write(snap, "kern.sqlite3")
                media = settings.MEDIA_ROOT
                for root, _dirs, files in os.walk(media):
                    for f in files:
                        full = os.path.join(root, f)
                        z.write(full, "media/" + os.path.relpath(full, media).replace(os.sep, "/"))
            os.replace(partial, path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        prune()
        return info(path)


def info(path) -> dict:
    st = os.stat(path)
    kind = "manual"
    m = re.search(r"-([a-z]+)\.zip$", os.path.basename(path))
    if m:
        kind = m.group(1)
    return {"name": os.path.basename(path), "size": st.st_size,
            "created_at": dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(), "kind": kind}


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    items = [info(BACKUP_DIR / n) for n in os.listdir(BACKUP_DIR) if NAME_RE.match(n)]
    return sorted(items, key=lambda i: i["name"], reverse=True)


def path_for(name: str):
    if not NAME_RE.match(name or ""):
        raise FileNotFoundError(name)
    p = BACKUP_DIR / name
    if not p.exists():
        raise FileNotFoundError(name)
    return p


def prune(keep_auto: int = 7, keep_safety: int = 3) -> None:
    items = list_backups()
    for kind, keep in (("auto", keep_auto), ("prerestore", keep_safety)):
        for i in [x for x in items if x["kind"] == kind][keep:]:
            os.remove(BACKUP_DIR / i["name"])


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
    safety = create("prerestore")
    with _lock:
        tmpdir = tempfile.mkdtemp(dir=settings.DATA_DIR)
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extract("kern.sqlite3", tmpdir)
                media_tmp = os.path.join(tmpdir, "media")
                os.makedirs(media_tmp, exist_ok=True)
                for n in z.namelist():
                    if n.startswith("media/") and not n.endswith("/"):
                        target = os.path.join(media_tmp, n[len("media/"):])
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with z.open(n) as src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)
            db_file = os.path.join(tmpdir, "kern.sqlite3")
            check = sqlite3.connect(db_file)
            ok = check.execute("PRAGMA integrity_check").fetchone()[0]
            has = check.execute("SELECT count(*) FROM sqlite_master WHERE name='notes_document'").fetchone()[0]
            if ok != "ok" or not has:
                check.close()
                raise ValueError("The database in this backup is damaged.")
            # Copy pages into the live database in place: other connections stay valid.
            connection.ensure_connection()
            live = connection.connection
            check.backup(live)
            check.close()
            connection.close()
            media = str(settings.MEDIA_ROOT)
            old = media + ".before-restore"
            shutil.rmtree(old, ignore_errors=True)
            if os.path.exists(media):
                os.replace(media, old)
            os.replace(media_tmp, media)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    call_command("migrate", interactive=False, verbosity=0)  # backups from older versions
    return {"restored": manifest, "safety_backup": safety["name"]}


def maybe_auto_backup() -> None:
    """Daily automatic backup, started in the background when the app is used."""
    from .models import Setting
    cfg = (Setting.objects.filter(key="data").values_list("value", flat=True).first() or {})
    if isinstance(cfg, dict) and cfg.get("auto_backup") is False:
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
            connection.close()

    threading.Thread(target=run, daemon=True).start()


def storage() -> dict:
    def size(path):
        total = 0
        for root, _d, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    db = _db_path()
    db_size = sum(os.path.getsize(p) for p in (db, db + "-wal") if os.path.exists(p))
    from .models import Attachment, Block, Card, Database, Document, DocVersion, Task
    return {
        "database_bytes": db_size,
        "media_bytes": size(settings.MEDIA_ROOT),
        "backups_bytes": size(BACKUP_DIR) if BACKUP_DIR.exists() else 0,
        "counts": {
            "pages": Document.objects.filter(entry_of__isnull=True, trashed_at__isnull=True).count(),
            "entries": Document.objects.filter(entry_of__isnull=False, trashed_at__isnull=True).count(),
            "databases": Database.objects.count(), "blocks": Block.objects.count(),
            "cards": Card.objects.count(), "tasks": Task.objects.count(), "files": Attachment.objects.count(),
            "versions": DocVersion.objects.count(),
            "trashed": Document.objects.filter(trashed_at__isnull=False).count(),
        },
        "data_dir": str(settings.DATA_DIR),
    }
