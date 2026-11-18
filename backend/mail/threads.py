"""Conversation threading.

An incremental take on the JWZ algorithm: a message joins every thread that
it references (References / In-Reply-To), that references it (a child that
arrived first), or that holds another copy of it (same Message-ID). Several
matches mean the message bridges two threads, which are merged. With no
links, a reply-looking subject ("Re: ...") joins a recent thread with the
same normalized subject and a shared participant.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from .models import FolderRole, Message, MessageReference, Thread
from .parsing import is_reply_subject

SUBJECT_WINDOW = timedelta(days=45)
MIN_SUBJECT_LEN = 4


def _participants(m: Message) -> set[str]:
    addrs = {m.from_addr}
    for field in (m.to_addrs, m.cc_addrs):
        addrs.update(a.get("addr", "") for a in field or [])
    addrs.discard("")
    return addrs


@transaction.atomic
def assign_thread(message: Message, reply_subject: bool) -> Thread:
    keys = set(message.references or [])
    if message.in_reply_to:
        keys.add(message.in_reply_to)
    keys.discard(message.message_key)

    thread_ids: set[int] = set()
    if keys:
        thread_ids.update(
            Message.objects.filter(message_key__in=keys, thread__isnull=False)
            .exclude(pk=message.pk).values_list("thread_id", flat=True)
        )
    thread_ids.update(
        MessageReference.objects.filter(key=message.message_key, message__thread__isnull=False)
        .exclude(message_id=message.pk).values_list("message__thread_id", flat=True)
    )
    thread_ids.update(
        Message.objects.filter(message_key=message.message_key, thread__isnull=False)
        .exclude(pk=message.pk).values_list("thread_id", flat=True)
    )

    # Subject fallback: either this message or the candidate must look like a
    # reply ("Re: ..."), they must share a participant and be close in time.
    if not thread_ids and len(message.subject_norm) >= MIN_SUBJECT_LEN:
        window = Q(sort_date__gte=message.sort_date - SUBJECT_WINDOW) & Q(
            sort_date__lte=message.sort_date + SUBJECT_WINDOW
        )
        mine = _participants(message)
        for cand in (
            Message.objects.filter(window, subject_norm=message.subject_norm, thread__isnull=False)
            .exclude(pk=message.pk).order_by("-sort_date")[:20]
        ):
            if not (reply_subject or is_reply_subject(cand.subject)):
                continue
            if mine & _participants(cand):
                thread_ids.add(cand.thread_id)
                break

    if not thread_ids:
        thread = Thread.objects.create(subject=message.subject)
    else:
        ordered = sorted(thread_ids)
        thread = Thread.objects.get(pk=ordered[0])
        others = ordered[1:]
        if others:
            Message.objects.filter(thread_id__in=others).update(thread=thread)
            Thread.objects.filter(pk__in=others).delete()
    message.thread = thread
    message.save(update_fields=["thread"])
    return thread


def refresh_thread(thread_id: int | None) -> None:
    """Recompute denormalized thread fields from its messages."""
    if thread_id is None:
        return
    msgs = list(
        Message.objects.filter(thread_id=thread_id)
        .select_related("folder")
        .order_by("sort_date", "id")
    )
    if not msgs:
        Thread.objects.filter(pk=thread_id).delete()
        return
    visible = [m for m in msgs if m.folder.role not in (FolderRole.TRASH, FolderRole.JUNK)] or msgs
    keys = {}
    for m in visible:
        keys.setdefault((m.message_key, m.blob_id), m)
    unique = list(keys.values())
    from .identity import my_addresses

    me = my_addresses()
    participants, seen = [], set()
    for m in unique:
        if m.from_addr and m.from_addr not in seen:
            seen.add(m.from_addr)
            participants.append({"name": m.from_name, "addr": m.from_addr})
    # Recipients of my own messages, so a conversation I started can show
    # "To: Alice" instead of my own name.
    for m in unique:
        if m.from_addr in me:
            for a in (m.to_addrs or []) + (m.cc_addrs or []):
                if a.get("addr") and a["addr"] not in seen and a["addr"] not in me:
                    seen.add(a["addr"])
                    participants.append({"name": a.get("name", ""), "addr": a["addr"], "to": True})
    order = {"high": 3, "medium": 2, "low": 1, "": 0}
    risk = max((m.risk_level for m in unique), key=lambda r: order.get(r, 0), default="")
    label_ids = sorted(
        set(
            Message.labels.through.objects.filter(message_id__in=[m.pk for m in msgs])
            .values_list("label_id", flat=True)
        )
    )
    latest = unique[-1]
    Thread.objects.filter(pk=thread_id).update(
        subject=unique[0].subject or latest.subject,
        last_date=latest.sort_date,
        message_count=len(unique),
        unread_count=sum(1 for m in unique if not m.seen),
        starred=any(m.flagged for m in unique),
        has_attachments=any(m.has_attachments for m in unique),
        participants=participants[:12],
        snippet=latest.snippet,
        risk_level=risk,
        label_ids=label_ids,
    )
