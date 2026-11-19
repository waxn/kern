"""SSH public keys: parsing, validation and the records behind Kern's git-over-SSH server."""
import base64
import binascii

import asyncssh
from django.db import IntegrityError

from .models import SSHKey

# OpenSSH names of the key types we accept (no DSA, no hardware-token "sk-" keys).
ALLOWED = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-rsa")
MIN_RSA_BITS = 2048
MAX_KEYS_PER_USER = 100


def parse(text: str) -> tuple[str, str, str]:
    """(key type, normalized "type base64", SHA256 fingerprint) of a pasted public key line, or
    ValueError with a message fit to show. A trailing comment is dropped."""
    text = str(text or "").strip()
    if len(text) > 8192:
        raise ValueError("That is too long to be a public key.")
    if "PRIVATE KEY" in text:
        raise ValueError("That is a private key. Paste the public key (the .pub file) instead.")
    if "\n" in text or "\r" in text:
        raise ValueError("Paste a single public key line (the contents of your .pub file).")
    parts = text.split()
    if len(parts) < 2:
        raise ValueError("That does not look like a public key. It should start with ssh-ed25519, ecdsa-sha2-… or ssh-rsa.")
    kind, b64 = parts[0], parts[1]
    if kind not in ALLOWED:
        raise ValueError(f"Unsupported key type {kind[:40]!r}. Use ed25519, ECDSA or RSA (2048 bits or more).")
    try:
        base64.b64decode(b64, validate=True)
        key = asyncssh.import_public_key(f"{kind} {b64}")
    except (binascii.Error, ValueError, asyncssh.KeyImportError):
        raise ValueError("That is not a valid public key.")
    if key.get_algorithm() != kind:
        raise ValueError("That is not a valid public key.")
    if kind == "ssh-rsa" and key.pyca_key.key_size < MIN_RSA_BITS:
        raise ValueError(f"RSA keys must be at least {MIN_RSA_BITS} bits.")
    return kind, f"{kind} {b64}", key.get_fingerprint("sha256")


def add(user, title: str, public_key: str, repo: str = "", read_only: bool = False) -> SSHKey:
    title = " ".join(str(title or "").split())[:80]
    if not title:
        raise ValueError("Give the key a title.")
    kind, norm, fp = parse(public_key)
    if SSHKey.objects.filter(user=user).count() >= MAX_KEYS_PER_USER:
        raise ValueError("Too many keys. Remove some first.")
    if SSHKey.objects.filter(fingerprint=fp).exists():
        raise ValueError("That key is already registered on this server.")
    try:
        return SSHKey.objects.create(user=user, repo=repo, title=title, key_type=kind, public_key=norm,
                                     fingerprint=fp, read_only=bool(read_only) if repo else False)
    except IntegrityError:
        raise ValueError("That key is already registered on this server.")


def as_json(k: SSHKey) -> dict:
    return {
        "id": k.id, "title": k.title, "type": k.key_type, "fingerprint": k.fingerprint,
        "repo": k.repo or None, "read_only": k.read_only,
        "created": k.created.isoformat(), "last_used": k.last_used.isoformat() if k.last_used else None,
    }


def delete_for_repo(user_id: int, repo: str) -> None:
    """A deleted repository takes its deploy keys with it."""
    SSHKey.objects.filter(user_id=user_id, repo=repo).delete()
