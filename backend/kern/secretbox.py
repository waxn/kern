"""Encryption at rest for the few secrets Kern must keep in a database:
mail account passwords and two-factor seeds.

SECURITY (read carefully): the key is a file outside every database, by
default ``DATA_DIR/secrets/kern.key`` (created on first use, mode 0600), or
the file named by ``KERN_SECRET_BOX_KEY_FILE`` (e.g. a Docker secret). A copy
of a database or a backup zip alone therefore can't reveal these secrets.
Losing the key means re-entering mail passwords and setting up two-factor
again; nothing else is affected.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_lock = threading.Lock()
_fernet: Fernet | None = None


class SecretBoxError(ValueError):
    pass


def key_path() -> Path:
    override = os.environ.get("KERN_SECRET_BOX_KEY_FILE")
    return Path(override) if override else Path(settings.DATA_DIR) / "secrets" / "kern.key"


def _load() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        path = key_path()
        if not path.exists():
            if os.environ.get("KERN_SECRET_BOX_KEY_FILE"):
                raise SecretBoxError(f"Key file {path} does not exist.")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
        _fernet = Fernet(path.read_bytes().strip())
        return _fernet


def encrypt(value: str) -> str:
    return _load().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _load().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError("Could not decrypt a stored secret (was the key file replaced?).") from exc


def reset_for_tests() -> None:
    global _fernet
    _fernet = None
