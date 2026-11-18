"""Snoozing conversations.

Snooze: the conversation's messages move to a "Snoozed" folder on the
server (so other clients stop showing them in the Inbox too) and a Snooze row
remembers when to bring them back. The sync worker calls wake_due() every
second; at wake time the messages return to the Inbox, the newest one is
marked unread, and a "snooze_wake" event notifies the browser. A new reply
to a snoozed conversation wakes it early.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import actions, events
from .models import Folder, FolderRole, Message, Snooze, SnoozeStatus, Thread

MIN_DELAY = timedelta(minutes=1)
MAX_DELAY = timedelta(days=5 * 365)


class SnoozeError(ValueError):
    pass


def active_for_threads(thread_ids) -> dict[int, Snooze]:
    out: dict[int, Snooze] = {}
    for s in Snooze.objects.filter(status=SnoozeStatus.ACTIVE, thread_id__in=list(thread_ids)):
        out[s.thread_id] = s
    return out


@transaction.atomic
def snooze_thread(thread: Thread, context: Folder | None, until) -> Snooze:
    now = timezone.now()
    if until is None or timezone.is_naive(until):
        raise SnoozeError("Pick a time to snooze until.")
    if until < now + MIN_DELAY:
        raise SnoozeError("Pick a time in the future.")
    if until > now + MAX_DELAY:
        raise SnoozeError("That's a bit far away.")
    snoozed = actions.role_folder(FolderRole.SNOOZED)
    skip = (FolderRole.SENT, FolderRole.DRAFTS, FolderRole.TRASH, FolderRole.JUNK, FolderRole.SNOOZED)
    msgs = list(Message.objects.filter(thread=thread).select_related("folder"))
    if context is not None and context.role != FolderRole.SNOOZED:
        movable = [m for m in msgs if m.folder_id == context.pk]
    else:
        movable = [m for m in msgs if m.folder.role == FolderRole.INBOX]
    movable = [m for m in movable if m.folder.role not in skip]
    already = Snooze.objects.filter(status=SnoozeStatus.ACTIVE, thread=thread)
    if not movable and not already.exists():
        raise SnoozeError("Nothing to snooze here.")
    # Re-snoozing just changes the time.
    already.update(status=SnoozeStatus.CANCELLED)
    s = Snooze.objects.create(
        thread=thread,
        message_keys=sorted({m.message_key for m in msgs}),
        subject=thread.subject[:2000],
        wake_at=until,
    )
    if movable:
        actions.move_messages(movable, snoozed)
    events.emit("update", threads=[thread.pk])
    return s


@transaction.atomic
def unsnooze(s: Snooze, *, reason: str) -> bool:
    """reason: "due" (time's up), "reply" (new message) or "manual"."""
    locked = Snooze.objects.select_for_update().get(pk=s.pk)
    if locked.status != SnoozeStatus.ACTIVE:
        return False
    msgs = list(
        Message.objects.filter(message_key__in=locked.message_keys, folder__role=FolderRole.SNOOZED)
        .select_related("folder")
    )
    locked.woken_at = timezone.now()
    if not msgs:
        # The messages were moved out of Snoozed some other way.
        locked.status = SnoozeStatus.CANCELLED
        locked.save(update_fields=["status", "woken_at"])
        return False
    locked.status = SnoozeStatus.WOKEN
    locked.save(update_fields=["status", "woken_at"])
    actions.move_messages(msgs, actions.role_folder(FolderRole.INBOX))
    if reason in ("due", "reply"):
        newest = max(msgs, key=lambda m: (m.sort_date, m.pk))
        if newest.seen:
            actions.set_flags([newest], remove=["\\Seen"])
        events.emit("snooze_wake", thread=newest.thread_id, reason=reason)
    return True


def wake_due(now=None) -> int:
    now = now or timezone.now()
    n = 0
    for s in Snooze.objects.filter(status=SnoozeStatus.ACTIVE, wake_at__lte=now)[:100]:
        if unsnooze(s, reason="due"):
            n += 1
    return n


def wake_for_new_message(message: Message) -> None:
    if message.thread_id is None:
        return
    keys = set(Message.objects.filter(thread_id=message.thread_id).values_list("message_key", flat=True))
    for s in Snooze.objects.filter(status=SnoozeStatus.ACTIVE):
        if s.thread_id == message.thread_id or keys & set(s.message_keys):
            unsnooze(s, reason="reply")
