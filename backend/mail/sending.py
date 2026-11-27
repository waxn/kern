"""Composing and sending mail."""

from __future__ import annotations

import email.utils
import html as _html
import mimetypes
import re
from datetime import timedelta
from email.message import EmailMessage
from email.policy import SMTP

import nh3
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import actions, events, outbox, parsing, store
from .identity import my_addresses, my_domain
from .models import Attachment, Draft, DraftStatus, Folder, FolderRole, Message, OpStatus, OutboxOp
from .account import cfg as _mail_cfg

COMPOSE_TAGS = {"a", "b", "strong", "i", "em", "u", "s", "strike", "br", "p", "div", "span",
                "ul", "ol", "li", "blockquote", "pre", "code", "h1", "h2", "h3", "hr", "sub", "sup"}
COMPOSE_ATTRS = {"a": {"href"}, "blockquote": {"type"}, "*": {"style"}, "span": {"style"}, "div": {"style"}}


class ComposeError(ValueError):
    pass


def clean_compose_html(markup: str) -> str:
    return nh3.clean(markup or "", tags=COMPOSE_TAGS, attributes=COMPOSE_ATTRS,
                     url_schemes={"http", "https", "mailto"}, link_rel=None,
                     clean_content_tags={"script", "style"})


def validate_recipients(items) -> list[dict]:
    if isinstance(items, str):
        # "Ada <ada@x.org>, b@y.org" from a plain field, not one character at a time.
        items = [{"name": n, "addr": a} for n, a in email.utils.getaddresses([items]) if n or a]
    elif not isinstance(items, (list, tuple)):
        items = [] if items is None else [items]
    out = []
    for item in items:
        if isinstance(item, dict):
            name, addr = str(item.get("name", "")), str(item.get("addr", ""))
        else:
            name, addr = email.utils.parseaddr(str(item))
        name = re.sub(r"[\r\n\x00]", " ", name).strip()[:200]
        addr = re.sub(r"\s", "", addr)
        if not re.fullmatch(r"[^@\s<>()\[\],;:\"]+@[^@\s<>()\[\],;:\"]+\.[^@\s<>()\[\],;:\"]+", addr):
            raise ComposeError(f"Invalid email address: {addr or item!r}")
        out.append({"name": name, "addr": addr})
    if len(out) > 500:
        raise ComposeError("Too many recipients.")
    return out


def drafts_folder() -> Folder:
    return actions.role_folder(FolderRole.DRAFTS)


def new_message_id() -> str:
    return email.utils.make_msgid(domain=my_domain()).strip("<>")


def _fmt(addrs: list[dict]) -> str:
    return ", ".join(email.utils.formataddr((a.get("name") or "", a["addr"])) for a in addrs)


HTML_WRAPPER = (
    "<!doctype html><html><head><meta charset=\"utf-8\"></head>"
    "<body><div style=\"font-family:Arial,'Liberation Sans','DejaVu Sans',sans-serif;"
    "font-size:15px;line-height:1.5;color:#222222\">{body}</div></body></html>"
)


def _sender(draft: Draft) -> tuple[str, str]:
    """(address, display name) the message is from: a "send as" address when one is picked."""
    from . import identities, preferences

    account_addr = _mail_cfg()["USERNAME"]
    if draft.from_addr and draft.from_addr.lower() != account_addr.lower():
        i = identities.find(draft.from_addr)
        if i is not None:
            return i.address, i.name or preferences.from_name() or ""
        aliases = {a.lower(): a for a in _mail_cfg()["ALIASES"]}
        if draft.from_addr.lower() in aliases:
            return aliases[draft.from_addr.lower()], preferences.from_name() or ""
    return account_addr, preferences.from_name() or ""


def build_mime(draft: Draft, *, for_draft: bool = False) -> bytes:
    cfg = _mail_cfg()
    msg = EmailMessage(policy=SMTP)
    from . import preferences

    sender, name = _sender(draft)
    msg["From"] = email.utils.formataddr((name, sender))
    if draft.to_addrs:
        msg["To"] = _fmt(draft.to_addrs)
    if draft.cc_addrs:
        msg["Cc"] = _fmt(draft.cc_addrs)
    if for_draft and draft.bcc_addrs:
        msg["Bcc"] = _fmt(draft.bcc_addrs)  # kept in the draft copy only
    msg["Subject"] = re.sub(r"[\r\n]+", " ", draft.subject or "")
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = f"<{draft.message_id}>"
    if draft.in_reply_to_key:
        msg["In-Reply-To"] = f"<{draft.in_reply_to_key}>"
    if draft.references:
        msg["References"] = " ".join(f"<{r}>" for r in draft.references[-30:])
    body_html = clean_compose_html(draft.body_html)
    text = parsing.html_to_text(body_html) or ""
    msg.set_content(text, subtype="plain", charset="utf-8")
    msg.add_alternative(HTML_WRAPPER.format(body=body_html), subtype="html", charset="utf-8")

    for up in draft.uploads.all().order_by("id"):
        maintype, _, subtype = (up.content_type or "application/octet-stream").partition("/")
        msg.add_attachment(store.get_upload(up.sha256), maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=up.filename)
    if draft.forward_attachments_of_id and draft.forward_attachment_ids:
        src = draft.forward_attachments_of
        raw = store.get(src.blob_id)
        for att in Attachment.objects.filter(message=src, pk__in=draft.forward_attachment_ids):
            part = parsing.find_part(raw, att.part_index)
            if part is None:
                continue
            maintype, _, subtype = att.content_type.partition("/")
            if att.content_type == "message/rfc822":
                maintype, subtype = "application", "octet-stream"
            msg.add_attachment(part.payload(), maintype=maintype or "application",
                               subtype=subtype or "octet-stream", filename=att.filename)
    return msg.as_bytes()


def build_for_send(draft: Draft) -> tuple[bytes, str, list[str]]:
    # Someone in both To and Cc (or Bcc) gets one copy.
    first: dict[str, str] = {}
    for a in draft.to_addrs + draft.cc_addrs + draft.bcc_addrs:
        first.setdefault(a["addr"].lower(), a["addr"])
    recipients = list(first.values())
    if not recipients:
        raise ComposeError("No recipients.")
    return build_mime(draft), _sender(draft)[0], recipients


MAX_SCHEDULE = timedelta(days=366)


def queue_send(draft: Draft, at=None) -> Draft:
    """Send after the undo window, or at `at` ("send later")."""
    if draft.status not in (DraftStatus.EDITING, DraftStatus.FAILED):
        raise ComposeError("This message is already being sent.")
    validate_recipients(draft.to_addrs + draft.cc_addrs + draft.bcc_addrs)
    if not (draft.to_addrs or draft.cc_addrs or draft.bcc_addrs):
        raise ComposeError("Add at least one recipient.")
    from . import preferences

    now = timezone.now()
    delay = preferences.undo_seconds()
    scheduled = at is not None and at > now + timedelta(seconds=max(delay, 30))
    if at is not None and at > now + MAX_SCHEDULE:
        raise ComposeError("You can schedule up to a year ahead.")
    if scheduled:
        delay = (at - now).total_seconds()
    with transaction.atomic():
        draft.status = DraftStatus.SCHEDULED if scheduled else DraftStatus.QUEUED
        draft.error = ""
        draft.send_at = now + timedelta(seconds=delay)
        draft.save(update_fields=["status", "error", "send_at"])
        # Drop pending autosaves; they'd re-create a server draft.
        OutboxOp.objects.filter(kind="save_draft", status=OpStatus.PENDING, payload__draft=draft.pk).update(
            status=OpStatus.CANCELLED)
        if scheduled and draft.server_uid and draft.server_folder_id:
            # Out of the server's Drafts folder while it waits, so it can't be
            # opened and sent a second time from another mail app.
            outbox.enqueue("delete_server_draft", folder=draft.server_folder_id,
                           uidvalidity=draft.server_uidvalidity, uid=draft.server_uid)
            draft.server_folder, draft.server_uidvalidity, draft.server_uid = None, None, None
            draft.save(update_fields=["server_folder", "server_uidvalidity", "server_uid"])
        outbox.enqueue("send", delay=delay, draft=draft.pk)
    return draft


def unschedule(draft: Draft) -> bool:
    """Cancel a scheduled send; the draft goes back to editing."""
    with transaction.atomic():
        d = Draft.objects.select_for_update().get(pk=draft.pk)
        if d.status != DraftStatus.SCHEDULED:
            return False
        OutboxOp.objects.filter(kind="send", status=OpStatus.PENDING, payload__draft=d.pk).update(
            status=OpStatus.CANCELLED)
        d.status, d.send_at = DraftStatus.EDITING, None
        d.save(update_fields=["status", "send_at"])
        # Put a copy back in the server's Drafts folder.
        outbox.enqueue("save_draft", delay=2, draft=d.pk)
    return True


def undo_send(draft: Draft) -> bool:
    with transaction.atomic():
        d = Draft.objects.select_for_update().get(pk=draft.pk)
        if d.status != DraftStatus.QUEUED or (d.send_at and d.send_at <= timezone.now()):
            return False
        n = OutboxOp.objects.filter(kind="send", status=OpStatus.PENDING, payload__draft=d.pk).update(
            status=OpStatus.CANCELLED)
        if not n:
            return False
        d.status = DraftStatus.EDITING
        d.save(update_fields=["status"])
    return True


def after_send(draft: Draft, raw: bytes) -> None:
    """Called once SMTP accepted the message."""
    with transaction.atomic():
        draft.status = DraftStatus.SENT
        draft.save(update_fields=["status"])
        from . import identities

        # The account's server keeps its own copy only of mail that went through it.
        through_other = identities.own_server(_sender(draft)[0]) is not None
        if through_other or not _mail_cfg()["SERVER_SAVES_SENT"]:
            blob = store.put(raw)
            outbox.enqueue("append", folder=actions.role_folder(FolderRole.SENT).pk,
                           blob=blob.sha256, flags=["\\Seen"])
        if draft.server_uid and draft.server_folder_id:
            outbox.enqueue("delete_server_draft", folder=draft.server_folder_id,
                           uidvalidity=draft.server_uidvalidity, uid=draft.server_uid)
        if draft.in_reply_to_id and draft.mode in ("reply", "reply_all"):
            m = Message.objects.filter(pk=draft.in_reply_to_id).first()
            if m:
                actions.set_flags([m], add=["\\Answered"])
        elif draft.forward_attachments_of_id and draft.mode == "forward":
            m = Message.objects.filter(pk=draft.forward_attachments_of_id).first()
            if m:
                actions.set_flags([m], add=["$Forwarded"])
    from . import followups

    followups.create_for_sent_draft(draft, timezone.now())
    events.emit("sent", draft=draft.pk)


# --- Prefill for reply / reply-all / forward --------------------------------

def _prefixed(subject: str, prefix: str) -> str:
    s = subject or ""
    if re.match(rf"^\s*{prefix}\s*:", s, re.IGNORECASE):
        return s
    return f"{prefix}: {s}".strip()


def quote_html(m: Message, body_html: str) -> str:
    who = _html.escape(f"{m.from_name} <{m.from_addr}>" if m.from_name else m.from_addr)
    when = m.sort_date.strftime("%a, %d %b %Y at %H:%M") if m.sort_date else ""
    return (f"<p><br></p><div>On {when}, {who} wrote:</div>"
            f"<blockquote type=\"cite\" style=\"margin:0 0 0 .8ex;border-left:2px solid #ccc;padding-left:1ex\">"
            f"{body_html}</blockquote>")


def forward_header_html(m: Message) -> str:
    def esc(x):
        return _html.escape(x or "")
    to = ", ".join(a["addr"] for a in m.to_addrs or [])
    return ("<p><br></p><div>---------- Forwarded message ----------<br>"
            f"From: {esc(m.from_name)} &lt;{esc(m.from_addr)}&gt;<br>"
            f"Date: {esc(m.sort_date.strftime('%a, %d %b %Y %H:%M') if m.sort_date else '')}<br>"
            f"Subject: {esc(m.subject)}<br>To: {esc(to)}</div><br>")


def compose_prefill(m: Message, mode: str, quoted_body_html: str) -> dict:
    from . import identities

    me = my_addresses()
    # Answer from the address it was sent to (a "send as" address, e.g. a forwarded Gmail).
    to_me = [a.get("addr", "") for a in (m.to_addrs or []) + (m.cc_addrs or [])]
    to_me += [str((m.headers or {}).get(h, "")).strip("<> ") for h in ("delivered-to", "x-forwarded-to", "x-original-to")]
    reply_from = identities.for_reply(to_me)
    refs = list(m.references or [])
    if m.message_id and m.message_id not in refs:
        refs.append(m.message_id)
    if mode == "forward":
        return {
            "mode": "forward",
            "to": [], "cc": [],
            "subject": _prefixed(m.subject, "Fwd"),
            "from": reply_from,
            "body_html": forward_header_html(m) + quoted_body_html,
            "in_reply_to": m.pk,
            "references": [],
            "forward_attachments": [
                {"id": a.pk, "filename": a.filename, "size": a.size, "content_type": a.content_type}
                for a in m.attachments.all() if not a.inline
            ],
        }
    reply_to = m.reply_to or [{"name": m.from_name, "addr": m.from_addr}]
    if m.from_addr in me:  # replying to your own sent message: keep its recipients
        to = list(m.to_addrs)
    else:
        to = reply_to
    cc = []
    if mode == "reply_all":
        seen = {a["addr"] for a in to} | me
        for a in (m.to_addrs or []) + (m.cc_addrs or []):
            if a["addr"] not in seen:
                seen.add(a["addr"])
                cc.append(a)
    return {
        "mode": mode,
        "to": to,
        "cc": cc,
        "subject": _prefixed(m.subject, "Re"),
        "from": reply_from,
        "body_html": quote_html(m, quoted_body_html),
        "in_reply_to": m.pk,
        "references": refs,
        "forward_attachments": [],
    }


def guess_type(filename: str, declared: str) -> str:
    declared = (declared or "").lower()
    if declared and "/" in declared and declared != "application/octet-stream":
        return declared[:255]
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
