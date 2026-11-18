"""Settings → Mail: connect, test, change and disconnect this user's account.

SECURITY (read carefully): the password is write-only. It's encrypted with
kern/secretbox.py and never sent back to the browser; responses only say
whether one is stored. Hosts are checked by mail/hosts.py. Connecting needs
two-factor sign-in (mail/api/guard.py).
"""
from __future__ import annotations

import copy
import smtplib
import ssl

from django.db import transaction

from kern import secretbox

from .. import account, events, hosts
from ..imap.client import ImapClient
from ..imap.base import ServerError
from ..models import MailAccount, WorkerStatus
from .util import ApiError, api, body, iso

FIELDS = ("address", "login", "from_name", "imap_host", "imap_port", "smtp_host", "smtp_port",
          "smtp_security", "tls_verify", "server_saves_sent", "authserv_id", "aliases")


def _clean(data: dict, base: MailAccount) -> MailAccount:
    from ..sending import validate_recipients

    a = copy.copy(base)  # keeps the row identity; nothing is saved here
    a.aliases = list(base.aliases or [])
    if "address" in data:
        addr = str(data["address"] or "").strip().lower()
        if addr:
            validate_recipients([{"addr": addr, "name": ""}])
        a.address = addr[:320]
    for f in ("login", "from_name", "imap_host", "smtp_host", "authserv_id"):
        if f in data:
            v = str(data[f] or "").strip()
            if any(c in v for c in "\r\n\0"):
                raise ApiError(f"{f.replace('_', ' ')} can't contain line breaks.")
            setattr(a, f, v[:320])
    for f in ("imap_port", "smtp_port"):
        if f in data:
            try:
                setattr(a, f, int(data[f]))
            except (TypeError, ValueError):
                raise ApiError("Ports are numbers, like 993 or 465.") from None
    if "smtp_security" in data:
        if data["smtp_security"] not in ("ssl", "starttls"):
            raise ApiError("Sending security is either SSL/TLS or STARTTLS.")
        a.smtp_security = data["smtp_security"]
    for f in ("tls_verify", "server_saves_sent"):
        if f in data:
            setattr(a, f, bool(data[f]))
    if "aliases" in data:
        al = [str(x).strip().lower() for x in (data["aliases"] or []) if str(x).strip()][:20]
        if al:
            validate_recipients([{"addr": x, "name": ""} for x in al])
        a.aliases = al
    return a


def status_json(a: MailAccount | None) -> dict:
    from accounts import site

    ws = WorkerStatus.objects.filter(pk=1).first()
    return {
        "allowed": bool(site.get_all().get("allow_mail", True)),
        "connected": bool(a and a.enabled and a.password_enc),
        "account": None if not a else {
            **{f: getattr(a, f) for f in FIELDS}, "enabled": a.enabled, "has_password": bool(a.password_enc),
            "updated": iso(a.updated),
        },
        "worker": None if not ws else {"state": ws.state, "detail": ws.detail, "heartbeat": iso(ws.heartbeat),
                                       "lastError": ws.last_error, "lastErrorAt": iso(ws.last_error_at)},
    }


@api()
def account_status(request):
    """Open without two-factor (guard.OPEN): Settings shows what's needed."""
    from accounts import totp

    out = status_json(account.get())
    out["two_factor"] = {"enabled": totp.enabled(request.user), "session_verified": totp.session_verified(request)}
    if not out["two_factor"]["session_verified"]:
        out["account"] = None if not out["account"] else {"address": out["account"]["address"]}
        out["worker"] = None
    return out


def _try_connect(a: MailAccount, pw: str) -> None:
    hosts.check(a.imap_host, a.imap_port)
    hosts.check(a.smtp_host, a.smtp_port)
    login = a.login or a.address
    try:
        ImapClient(a.imap_host, a.imap_port, login, pw, verify_tls=a.tls_verify, timeout=20).close()
    except ServerError as exc:
        raise ApiError(f"Couldn't sign in to {a.imap_host}: {exc}") from None
    ctx = ssl.create_default_context()
    if not a.tls_verify:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        if a.smtp_security == "starttls":
            c = smtplib.SMTP(a.smtp_host, a.smtp_port, timeout=20)
            c.starttls(context=ctx)
        else:
            c = smtplib.SMTP_SSL(a.smtp_host, a.smtp_port, timeout=20, context=ctx)
        try:
            c.login(login, pw)
        finally:
            try:
                c.quit()
            except smtplib.SMTPException:
                pass
    except (smtplib.SMTPException, OSError) as exc:
        raise ApiError(f"Reading works, but sending through {a.smtp_host} failed: {exc}") from None


@api(("POST",))
def account_test(request):
    data = body(request)
    base = account.get() or MailAccount(pk=1)
    a = _clean(data, base)
    pw = str(data.get("password") or "") or (account.password() if base.password_enc else "")
    if not (a.address and a.imap_host and a.smtp_host and pw):
        raise ApiError("Fill in the address, both servers and the password first.")
    try:
        _try_connect(a, pw)
    except hosts.HostNotAllowed as exc:
        raise ApiError(str(exc)) from None
    return {"ok": True}


@api(("PUT", "DELETE"))
def account_detail(request):
    from accounts import site

    if request.method == "DELETE":
        # Disconnect: stop syncing and forget the password. ?forget=1 also removes the
        # local copy of the mail (the mail server keeps everything).
        with transaction.atomic():
            a = account.get()
            if a:
                a.enabled, a.password_enc, a.version = False, "", a.version + 1
                a.save()
        account.invalidate()
        if request.GET.get("forget") == "1":
            from .. import lifecycle

            lifecycle.forget_local_mail()
        events.emit("account", connected=False)
        return status_json(account.get())

    if not site.get_all().get("allow_mail", True):
        raise ApiError("An administrator has turned mail off on this server.", 403, "forbidden")
    data = body(request)
    base = account.get() or MailAccount(pk=1)
    a = _clean(data, base)
    pw = str(data.get("password") or "")
    if not (a.address and a.imap_host and a.smtp_host):
        raise ApiError("Fill in the address and both servers.")
    if not pw and not base.password_enc:
        raise ApiError("Enter the password for this mail account.")
    try:
        hosts.check(a.imap_host, a.imap_port)
        hosts.check(a.smtp_host, a.smtp_port)
    except hosts.HostNotAllowed as exc:
        raise ApiError(str(exc)) from None
    changed_server = any(getattr(a, f) != getattr(base, f) for f in ("address", "login", "imap_host", "imap_port"))
    if changed_server and base.pk and base.address and a.address != base.address:
        # A different mailbox: the local copy belongs to the old one.
        from .. import lifecycle

        lifecycle.forget_local_mail()
    if pw:
        a.password_enc = secretbox.encrypt(pw)
    a.enabled = bool(data.get("enabled", True))
    a.version = base.version + 1
    a.save()
    account.invalidate()
    events.emit("account", connected=a.enabled)
    return status_json(a)
