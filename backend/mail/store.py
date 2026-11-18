"""Content-addressed raw message storage on the mailstore volume."""

from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from pathlib import Path

from django.conf import settings

from .models import Blob


def _root() -> Path:
    # The active user's folder (kern/tenancy.py): DATA_DIR/users/<id>/mail/.
    from kern import tenancy

    return tenancy.data_dir() / "mail"


def blob_path(sha: str) -> Path:
    return _root() / "blobs" / sha[:2] / sha[2:4] / f"{sha}.eml.gz"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def put(raw: bytes) -> Blob:
    sha = hashlib.sha256(raw).hexdigest()
    path = blob_path(sha)
    if not path.exists():
        _atomic_write(path, gzip.compress(raw, compresslevel=6))
    blob, _ = Blob.objects.get_or_create(sha256=sha, defaults={"size": len(raw)})
    return blob


def get(sha: str) -> bytes:
    with gzip.open(blob_path(sha), "rb") as fh:
        return fh.read()


# --- Uploaded attachments ----------------------------------------------------

def upload_path(sha: str) -> Path:
    return _root() / "uploads" / sha[:2] / sha


def put_upload(data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    path = upload_path(sha)
    if not path.exists():
        _atomic_write(path, data)
    return sha


def get_upload(sha: str) -> bytes:
    return upload_path(sha).read_bytes()
