"""Follow-up nudges: "remind me if nobody replies".

A FollowUp watches one message you sent. The sync worker calls check_due()
every second; when due_at passes and nobody else has written in that
conversation since you sent it, the follow-up becomes "nudged" and a "nudge"
event notifies the browser. A reply before then closes it quietly. This is
all local state: nothing is changed on the mail server.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from . import events, taskbridge
from .identity import my_addresses
from .models import FollowUp, FollowUpStatus, Message, Thread

OPEN = (FollowUpStatus.WAITING, FollowUpStatus.NUDGED)


class FollowUpError(ValueError):
    pass


def _thread_id(f: FollowUp) -> int | None:
    if f.thread_id and Thread.objects.filter(pk=f.thread_id).exists():
        return f.thread_id
    tid = Message.objects.filter(message_key=f.message_key, thread__isnull=False).values_list("thread_id", flat=True).first()
    if tid and tid != f.thread_id:
        FollowUp.objects.filter(pk=f.pk).update(thread_id=tid)
        f.thread_id = tid
    return tid


def has_reply(f: FollowUp) -> bool:
    tid = _thread_id(f)
    if not tid:
        return False
    me = my_addresses()
    return Message.objects.filter(thread_id=tid, sort_date__gt=f.sent_at).exclude(from_addr__in=me).exists()


def create_for_thread(thread: Thread, until) -> FollowUp:
    now = timezone.now()
    if until is None or timezone.is_naive(until) or until < now + timedelta(minutes=1):
        raise FollowUpError("Pick a time in the future.")
    me = my_addresses()
    mine = Message.objects.filter(thread=thread, from_addr__in=me).order_by("-sort_date").first()
    if mine is None:
        raise FollowUpError("Nudges are for conversations where you've written something.")
    for old in FollowUp.objects.filter(thread=thread, status__in=OPEN):
        close(old, FollowUpStatus.CANCELLED)
    f = FollowUp.objects.create(
        thread=thread, message_key=mine.message_key, subject=thread.subject[:2000],
        recipients=(mine.to_addrs or [])[:10], sent_at=mine.sort_date, due_at=until,
    )
    taskbridge.task_for_followup(f)
    return f


def create_for_sent_draft(draft, sent_at) -> FollowUp | None:
    if not draft.followup_at:
        return None
    thread = draft.in_reply_to.thread if draft.in_reply_to_id and draft.in_reply_to else None
    f = FollowUp.objects.create(
        thread=thread, message_key=draft.message_id, subject=draft.subject[:2000],
        recipients=(draft.to_addrs or [])[:10], sent_at=sent_at, due_at=draft.followup_at,
    )
    taskbridge.task_for_followup(f)
    return f


def close(f: FollowUp, status: str) -> None:
    """End a follow-up and its task: DONE after a reply (task completed),
    CANCELLED by the user (task removed)."""
    FollowUp.objects.filter(pk=f.pk).update(status=status)
    f.status = status
    taskbridge.followup_closed(f, replied=status == FollowUpStatus.DONE)


def move(f: FollowUp, until) -> None:
    FollowUp.objects.filter(pk=f.pk).update(status=FollowUpStatus.WAITING, due_at=until)
    f.status, f.due_at = FollowUpStatus.WAITING, until
    taskbridge.followup_moved(f)


def check_due(now=None) -> int:
    now = now or timezone.now()
    nudged = 0
    for f in FollowUp.objects.filter(status=FollowUpStatus.WAITING, due_at__lte=now)[:100]:
        if has_reply(f):
            close(f, FollowUpStatus.DONE)
            continue
        f.status = FollowUpStatus.NUDGED
        f.nudged_at = now
        f.save(update_fields=["status", "nudged_at"])
        events.emit("nudge", thread=_thread_id(f), followup=f.pk)
        nudged += 1
    return nudged


def on_new_message(message: Message) -> None:
    """Someone wrote in a conversation you were waiting on: close the nudge."""
    if message.thread_id is None or message.from_addr in my_addresses():
        return
    keys = set(Message.objects.filter(thread_id=message.thread_id).values_list("message_key", flat=True))
    closed = list(FollowUp.objects.filter(status__in=OPEN).filter(
        Q(thread_id=message.thread_id) | Q(message_key__in=keys)
    ))
    for f in closed:
        close(f, FollowUpStatus.DONE)
    if closed:
        events.emit("update", threads=[message.thread_id])


def open_for_threads(thread_ids) -> dict[int, FollowUp]:
    out: dict[int, FollowUp] = {}
    for f in FollowUp.objects.filter(status__in=OPEN, thread_id__in=list(thread_ids)):
        out[f.thread_id] = f
    return out
