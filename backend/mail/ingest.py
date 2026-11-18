"""Turning raw bytes from the server into Message rows."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.db import transaction

from . import events, labels, store, threads
from .models import Attachment, Folder, Message, MessageReference
from .parsing import is_reply_subject, normalize_subject, parse_message
from .pipeline import run_pipeline

log = logging.getLogger("kern.mail.ingest")

SYSTEM_FLAGS = {"\\seen", "\\flagged", "\\answered", "\\draft", "\\deleted", "\\recent"}


def split_flags(flags: list[str]) -> dict:
    low = {f.lower() for f in flags}
    keywords = sorted({f for f in flags if f.lower() not in SYSTEM_FLAGS and not f.startswith("\\")})
    return {
        "seen": "\\seen" in low,
        "flagged": "\\flagged" in low,
        "answered": "\\answered" in low,
        "is_draft": "\\draft" in low,
        "keywords": keywords,
    }


def apply_flags(message: Message, flags: list[str]) -> bool:
    """Update flag fields from a server flag list; returns True if changed."""
    new = split_flags(flags)
    changed = False
    for k, v in new.items():
        if getattr(message, k) != v:
            setattr(message, k, v)
            changed = True
    if changed:
        message.save(update_fields=list(new.keys()) + ["updated"])
        message.labels.set(labels.labels_from_keywords(new["keywords"]))
    return changed


def ingest_raw(folder: Folder, uid: int | None, uidvalidity: int | None, flags: list[str],
               internal_date: datetime | None, raw: bytes, *, initial: bool = False,
               refresh: set | None = None) -> Message:
    """Store one message. With `refresh` (a set), the conversation's summary
    isn't recomputed here; its id is added to the set so the caller can
    refresh each conversation once per batch (a big win for long threads
    during the first sync)."""

    def touch(thread_id):
        if refresh is not None:
            refresh.add(thread_id)
        else:
            threads.refresh_thread(thread_id)

    blob = store.put(raw)

    # A local move waiting for its new UID: same bytes, same folder, no UID yet.
    if uid is not None:
        pending = Message.objects.filter(server_folder=folder, uid__isnull=True, blob=blob).first()
        if pending is not None:
            pending.uid, pending.uidvalidity = uid, uidvalidity
            pending.save(update_fields=["uid", "uidvalidity", "updated"])
            apply_flags(pending, flags)
            touch(pending.thread_id)
            return pending

    pm = parse_message(raw)
    f = split_flags(flags)
    message_key = pm.message_id or f"synthetic:{blob.sha256}"
    sort_date = pm.date or internal_date or datetime.now(timezone.utc)
    # Distrust Date headers far from the server's receive time (spam often lies).
    if pm.date and internal_date and abs((pm.date - internal_date).total_seconds()) > 7 * 86400:
        sort_date = internal_date

    def addr_text(lst):
        return " ".join(f"{a['name']} {a['addr']}" for a in lst)

    with transaction.atomic():
        message = Message.objects.create(
            folder=folder,
            server_folder=folder,
            uid=uid,
            uidvalidity=uidvalidity,
            blob=blob,
            message_id=pm.message_id[:998],
            message_key=message_key[:998],
            in_reply_to=pm.in_reply_to[:998],
            references=pm.references,
            subject=pm.subject,
            subject_norm=normalize_subject(pm.subject),
            from_name=pm.from_name[:512],
            from_addr=pm.from_addr[:512],
            to_addrs=pm.to,
            cc_addrs=pm.cc,
            bcc_addrs=pm.bcc,
            reply_to=pm.reply_to,
            search_recipients=addr_text(pm.to + pm.cc + pm.bcc)[:20000],
            attachment_names=" ".join(a.filename for a in pm.attachments if not a.content_id or a.disposition == "attachment")[:5000],
            date=pm.date,
            internal_date=internal_date,
            sort_date=sort_date,
            size=len(raw),
            has_attachments=any(not (a.content_id and a.disposition == "inline") for a in pm.attachments),
            has_html=bool(pm.html),
            snippet=pm.snippet,
            body_text=pm.text,
            headers=pm.headers,
            parse_defects=pm.defects[:30],
            **f,
        )
        refs = set(pm.references)
        if pm.in_reply_to:
            refs.add(pm.in_reply_to)
        MessageReference.objects.bulk_create(
            [MessageReference(message=message, key=k[:998]) for k in refs if k != message_key]
        )
        Attachment.objects.bulk_create([
            Attachment(
                message=message,
                part_index=a.index,
                filename=a.filename,
                content_type=a.content_type[:255],
                size=len(a.payload()),
                content_id=a.content_id[:512],
                inline=bool(a.content_id) and a.disposition != "attachment",
            )
            for a in pm.attachments[:200]
        ])
        if f["keywords"]:
            message.labels.set(labels.labels_from_keywords(f["keywords"]))
        thread = threads.assign_thread(message, reply_subject=is_reply_subject(pm.subject))

    try:
        run_pipeline(message, pm, initial=initial)
    except Exception:  # a buggy stage must never lose mail
        log.exception("pipeline failed for message %s", message.pk)
    touch(message.thread_id)
    if not initial:
        events.emit("message", folder=message.folder_id, thread=thread.pk,
                    new=not message.seen and folder.role == "inbox")
    return message
