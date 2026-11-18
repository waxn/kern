"""Muting conversations: replies to a muted conversation skip the Inbox."""

from __future__ import annotations

from django.db import transaction

from . import actions
from .models import FolderRole, Message, Mute, Thread


def mute_for_thread(thread_id: int) -> Mute | None:
    if not thread_id:
        return None
    keys = set(Message.objects.filter(thread_id=thread_id).values_list("message_key", flat=True))
    for m in Mute.objects.all():
        if m.thread_id == thread_id or keys & set(m.message_keys):
            return m
    return None


@transaction.atomic
def mute(thread: Thread) -> Mute:
    existing = mute_for_thread(thread.pk)
    keys = sorted(set(Message.objects.filter(thread=thread).values_list("message_key", flat=True)))
    if existing:
        existing.message_keys = sorted(set(existing.message_keys) | set(keys))
        existing.thread = thread
        existing.save(update_fields=["message_keys", "thread"])
        m = existing
    else:
        m = Mute.objects.create(thread=thread, message_keys=keys, subject=thread.subject[:2000])
    # Take it out of the Inbox now too.
    inbox = list(Message.objects.filter(thread=thread, folder__role=FolderRole.INBOX))
    if inbox:
        actions.move_messages(inbox, actions.role_folder(FolderRole.ARCHIVE))
    return m


def unmute(thread: Thread, restore_to=None) -> bool:
    """Unmute; with restore_to (a Folder), also bring the archived messages
    back there (used by Undo, since muting archived them)."""
    m = mute_for_thread(thread.pk)
    if m:
        m.delete()
    if restore_to is not None:
        archived = list(Message.objects.filter(thread=thread, folder__role=FolderRole.ARCHIVE))
        if archived:
            actions.move_messages(archived, restore_to)
    return m is not None


def muted_thread_ids(thread_ids) -> set[int]:
    ids = set(thread_ids)
    if not ids or not Mute.objects.exists():
        return set()
    out = set()
    by_key = {}
    for tid, key in Message.objects.filter(thread_id__in=ids).values_list("thread_id", "message_key"):
        by_key.setdefault(key, set()).add(tid)
    for m in Mute.objects.all():
        if m.thread_id in ids:
            out.add(m.thread_id)
        for k in m.message_keys:
            out |= by_key.get(k, set())
    return out
