"""The signed-in user's mail account.

Each Kern user connects their own IMAP/SMTP account (Settings → Mail). The
settings live in that user's own database (``MailAccount``); the password is
encrypted with kern/secretbox.py, whose key is a file outside every database.
Everything that used to read Manifest's single ``settings.MAIL`` asks
``cfg()`` instead, which answers for whoever is active (kern/tenancy.py).
"""
from __future__ import annotations

import time

from django.conf import settings

from kern import secretbox, tenancy

# Server-wide tuning; per-account values come from MailAccount.
TUNING = {
    "POLL_SECONDS": 120,  # full folder sweep; INBOX is pushed via IDLE
    "FETCH_BATCH": 50,
    "SEND_UNDO_SECONDS": 8,
}

_cache: dict = {}
TTL = 5.0


def _key():
    if tenancy.testing():  # tests change settings.MAIL; make that part of the key
        return ("test", repr(sorted((getattr(settings, "MAIL", {}) or {}).items())))
    return tenancy.current_uid()


def get():
    from .models import MailAccount

    return MailAccount.objects.filter(pk=1).first()


def invalidate() -> None:
    if tenancy.testing():
        _cache.clear()
    else:
        _cache.pop(_key(), None)


def cfg() -> dict:
    """Manifest's MAIL settings, for the active user. USERNAME is "" when no
    account is connected (or it's switched off)."""
    k = _key()
    hit = _cache.get(k)
    now = time.monotonic()
    testing = tenancy.testing()
    if hit and now - hit[0] < TTL:
        return hit[1]
    a = get()
    on = bool(a and a.enabled and a.address)
    out = {
        **TUNING,
        **getattr(settings, "MAIL_TUNING", {}),
        "USERNAME": a.address if on else "",
        "LOGIN": (a.login or a.address) if on else "",
        "FROM_NAME": a.from_name if a else "",
        "IMAP_HOST": a.imap_host if a else "",
        "IMAP_PORT": a.imap_port if a else 993,
        "SMTP_HOST": a.smtp_host if a else "",
        "SMTP_PORT": a.smtp_port if a else 465,
        "SMTP_SECURITY": a.smtp_security if a else "ssl",
        "TLS_VERIFY": a.tls_verify if a else True,
        "SERVER_SAVES_SENT": a.server_saves_sent if a else False,
        "AUTHSERV_ID": a.authserv_id if a else "",
        "ALIASES": [x for x in (a.aliases if a else []) if x],
        "VERSION": a.version if a else 0,
    }
    if testing:  # tests override single values with settings.MAIL = {...}
        out.update(getattr(settings, "MAIL", {}) or {})
    _cache[k] = (now, out)
    return out


def password() -> str:
    a = get()
    if not a or not a.password_enc:
        return ""
    return secretbox.decrypt(a.password_enc)
