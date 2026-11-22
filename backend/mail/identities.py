"""Other addresses you send as ("Send mail as").

The common case: Gmail forwards everything to this mailbox (say Purelymail), and you want to
answer from the Gmail address without the mail showing up twice. Add the Gmail address here with
Gmail's SMTP server (smtp.gmail.com, port 465, an app password). Mail you send as it then:

* goes out through Gmail, so it's signed by Gmail and lands in inboxes, not spam;
* is saved once, in this mailbox's Sent folder (Gmail keeps its own copy in Gmail's Sent,
  which isn't forwarded, so nothing arrives here twice);
* replies come back to Gmail and are forwarded here like the rest.

An identity without its own SMTP server is sent through the account's server (an alias your
provider already lets you send as).

SECURITY: passwords are encrypted like the account's (kern/secretbox.py) and never sent to the
browser; SMTP hosts must be public (mail/hosts.py), checked when saved and at every send.
"""

from __future__ import annotations

import re
import smtplib
import ssl

from kern import secretbox

from . import hosts
from .models import MailIdentity

ADDR = re.compile(r"[^@\s<>()\[\],;:\"]+@[^@\s<>()\[\],;:\"]+\.[^@\s<>()\[\],;:\"]+")
MAX = 20


class IdentityError(ValueError):
    pass


def as_json(i: MailIdentity) -> dict:
    return {"id": i.id, "address": i.address, "name": i.name, "smtpHost": i.smtp_host, "smtpPort": i.smtp_port,
            "smtpSecurity": i.smtp_security, "login": i.login, "hasPassword": bool(i.password_enc),
            "tlsVerify": i.tls_verify, "ownServer": bool(i.smtp_host)}


def all_json() -> list[dict]:
    return [as_json(i) for i in MailIdentity.objects.order_by("address")]


_cache: dict = {}
TTL = 5.0


def _key():
    from kern import tenancy

    return "test" if tenancy.testing() else tenancy.current_uid()


def invalidate() -> None:
    _cache.pop(_key(), None)


def addresses() -> set[str]:
    """Every "send as" address, lower case (cached for a few seconds: asked on every list)."""
    import time

    k, now = _key(), time.monotonic()
    hit = _cache.get(k)
    if hit and now - hit[0] < TTL:
        return hit[1]
    out = {a.lower() for a in MailIdentity.objects.values_list("address", flat=True)}
    _cache[k] = (now, out)
    return out


def find(address: str) -> MailIdentity | None:
    if not address:
        return None
    return MailIdentity.objects.filter(address__iexact=address.strip()).first()


def save(data: dict, ident: MailIdentity | None = None) -> MailIdentity:
    from .account import cfg

    i = ident or MailIdentity()
    if "address" in data or ident is None:
        addr = re.sub(r"\s", "", str(data.get("address") or ""))
        if not ADDR.fullmatch(addr) or len(addr) > 320:
            raise IdentityError("Enter an email address like you@gmail.com.")
        if addr.lower() == cfg()["USERNAME"].lower():
            raise IdentityError("That's the account's own address already.")
        clash = MailIdentity.objects.filter(address__iexact=addr).exclude(pk=i.pk).exists()
        if clash:
            raise IdentityError("You already send as that address.")
        i.address = addr
    if "name" in data:
        i.name = " ".join(str(data.get("name") or "").split())[:200]
    if "smtpHost" in data:
        i.smtp_host = str(data.get("smtpHost") or "").strip().lower()[:255]
    if "smtpPort" in data:
        try:
            i.smtp_port = int(data.get("smtpPort") or 465)
        except (TypeError, ValueError):
            raise IdentityError("The port is a number, usually 465 or 587.") from None
        if not 1 <= i.smtp_port <= 65535:
            raise IdentityError("The port is a number, usually 465 or 587.")
    if "smtpSecurity" in data:
        if data["smtpSecurity"] not in ("ssl", "starttls"):
            raise IdentityError("Security is SSL/TLS or STARTTLS.")
        i.smtp_security = data["smtpSecurity"]
    if "login" in data:
        i.login = str(data.get("login") or "").strip()[:320]
    if "tlsVerify" in data:
        i.tls_verify = bool(data["tlsVerify"])
    if data.get("password"):
        i.password_enc = secretbox.encrypt(str(data["password"]))
    if i.smtp_host:
        try:
            hosts.check(i.smtp_host, i.smtp_port)
        except hosts.HostNotAllowed as exc:
            raise IdentityError(str(exc)) from exc
        if not i.password_enc:
            raise IdentityError("Enter the password for that server (for Gmail: an app password).")
    if ident is None and MailIdentity.objects.count() >= MAX:
        raise IdentityError("That's a lot of addresses. Remove one first.")
    i.save()
    invalidate()
    return i


def _context(verify: bool):
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect(i: MailIdentity, timeout: int = 60):
    hosts.check(i.smtp_host, i.smtp_port)  # again: DNS may have changed since it was saved
    if i.smtp_security == "starttls":
        client = smtplib.SMTP(i.smtp_host, i.smtp_port, timeout=timeout)
        client.starttls(context=_context(i.tls_verify))
    else:
        client = smtplib.SMTP_SSL(i.smtp_host, i.smtp_port, timeout=timeout, context=_context(i.tls_verify))
    client.login(i.login or i.address, secretbox.decrypt(i.password_enc))
    return client


def test(i: MailIdentity) -> None:
    if not i.smtp_host:
        return
    try:
        client = _connect(i, timeout=20)
    except hosts.HostNotAllowed as exc:
        raise IdentityError(str(exc)) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise IdentityError(f"Couldn't sign in to {i.smtp_host}: {exc}") from None
    try:
        client.quit()
    except smtplib.SMTPException:
        pass


def send(i: MailIdentity, envelope_from: str, recipients: list[str], raw: bytes) -> dict:
    """Send through the identity's own server. Same contract as SmtpSender.send."""
    client = _connect(i)
    try:
        refused = client.sendmail(envelope_from, recipients, raw)
        return {k: (v[0], v[1].decode("utf-8", "replace") if isinstance(v[1], bytes) else str(v[1]))
                for k, v in (refused or {}).items()}
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:
            pass


def own_server(address: str) -> MailIdentity | None:
    """The identity to send through, when this From address has a server of its own."""
    i = find(address)
    return i if i and i.smtp_host and i.password_enc else None


def for_reply(addresses_in_message: list[str]) -> str:
    """Answer from the address the mail was sent to: the first of yours among To/Cc/Delivered-To."""
    mine = {a.lower(): a for a in MailIdentity.objects.values_list("address", flat=True)}
    for a in addresses_in_message:
        hit = mine.get((a or "").lower())
        if hit:
            return hit
    return ""
