"""User actions on mail. Each one updates local rows right away (so the UI is
instant) and queues the matching server change in the outbox."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from . import events, labels as labels_mod, outbox, spam
from .identity import my_addresses
from .models import BlockKind, Folder, FolderRole, Label, Message, Thread
from .threads import refresh_thread

DEFAULT_NAMES = {
    FolderRole.INBOX: "INBOX",
    FolderRole.SENT: "Sent",
    FolderRole.DRAFTS: "Drafts",
    FolderRole.JUNK: "Junk",
    FolderRole.TRASH: "Trash",
    FolderRole.ARCHIVE: "Archive",
    FolderRole.SNOOZED: "Snoozed",
}

FLAG_FIELDS = {"\\seen": "seen", "\\flagged": "flagged", "\\answered": "answered", "\\draft": "is_draft"}


class ActionError(ValueError):
    pass


def role_folder(role: str) -> Folder:
    folder = Folder.objects.filter(role=role).first()
    if folder:
        return folder
    name = DEFAULT_NAMES[role]
    folder = Folder.objects.filter(name__iexact=name).first()
    if folder:
        folder.role = role
        folder.save(update_fields=["role"])
        return folder
    folder = Folder.objects.create(name=name, role=role, needs_create=True, exists_on_server=False)
    outbox.enqueue("create_folder", folder=folder.pk)
    return folder


def _touch(messages: Iterable[Message]) -> None:
    thread_ids = {m.thread_id for m in messages if m.thread_id}
    for tid in thread_ids:
        refresh_thread(tid)
    if thread_ids:
        events.emit("update", threads=sorted(thread_ids))


@transaction.atomic
def set_flags(messages: list[Message], add: list[str] = (), remove: list[str] = ()) -> None:
    add, remove = list(add), list(remove)
    if not messages or not (add or remove):
        return
    for m in messages:
        kws = set(m.keywords or [])
        for flag in add:
            field = FLAG_FIELDS.get(flag.lower())
            if field:
                setattr(m, field, True)
            else:
                kws.add(flag)
        for flag in remove:
            field = FLAG_FIELDS.get(flag.lower())
            if field:
                setattr(m, field, False)
            else:
                kws.discard(flag)
        m.keywords = sorted(kws)
        m.save(update_fields=["seen", "flagged", "answered", "is_draft", "keywords", "updated"])
    outbox.enqueue("flags", message_ids=[m.pk for m in messages], add=add, remove=remove)
    _touch(messages)


@transaction.atomic
def move_messages(messages: list[Message], dest: Folder) -> list[Message]:
    moved = [m for m in messages if m.folder_id != dest.pk]
    if not moved:
        return []
    for m in moved:
        m.folder = dest
        m.save(update_fields=["folder", "updated"])
    outbox.enqueue("move", message_ids=[m.pk for m in moved], dest=dest.pk)
    _touch(moved)
    return moved


@transaction.atomic
def delete_forever(messages: list[Message]) -> int:
    allowed = {FolderRole.TRASH, FolderRole.JUNK}
    targets = []
    for m in messages:
        if m.folder.role not in allowed:
            raise ActionError("Only messages in Trash or Junk can be deleted permanently.")
        if m.uid is None or m.server_folder_id != m.folder_id:
            raise ActionError("Some messages are still being moved. Try again in a moment.")
        targets.append(m)
    if not targets:
        return 0
    outbox.enqueue("expunge", locations=[[m.server_folder_id, m.uidvalidity, m.uid] for m in targets])
    thread_ids = {m.thread_id for m in targets}
    Message.objects.filter(pk__in=[m.pk for m in targets]).delete()
    for tid in thread_ids:
        refresh_thread(tid)
    events.emit("update", threads=sorted(t for t in thread_ids if t))
    return len(targets)


def set_labels(messages: list[Message], add: list[Label] = (), remove: list[Label] = ()) -> None:
    for m in messages:
        if add:
            m.labels.add(*add)
        if remove:
            m.labels.remove(*remove)
    set_flags(messages, add=[lb.keyword for lb in add], remove=[lb.keyword for lb in remove])


# --- Thread-level actions ----------------------------------------------------

def context_messages(thread: Thread, context: Folder | None, *, exclude_roles=()) -> list[Message]:
    qs = Message.objects.filter(thread=thread).select_related("folder")
    if context is not None:
        qs = qs.filter(folder=context)
    msgs = [m for m in qs if m.folder.role not in exclude_roles]
    return msgs


def archive(thread: Thread, context: Folder | None) -> None:
    """Gmail-style: take the conversation out of the Inbox (or out of the
    folder you're looking at)."""
    if context is not None and context.role == FolderRole.ARCHIVE:
        return
    src = context or role_folder(FolderRole.INBOX)
    move_messages(context_messages(thread, src), role_folder(FolderRole.ARCHIVE))


def trash(thread: Thread, context: Folder | None) -> None:
    msgs = context_messages(thread, context, exclude_roles=(FolderRole.TRASH,))
    move_messages(msgs, role_folder(FolderRole.TRASH))


def move_thread(thread: Thread, context: Folder | None, dest: Folder) -> None:
    msgs = context_messages(thread, context, exclude_roles=() if context else (FolderRole.SENT, FolderRole.DRAFTS, FolderRole.TRASH, FolderRole.JUNK))
    move_messages(msgs, dest)


def report_spam(thread: Thread, context: Folder | None, block: str = "") -> dict:
    """Move to Junk (server-side too, so the provider's filter can learn), mark
    $Junk, and optionally block the sender address or domain."""
    me = my_addresses()
    msgs = [m for m in context_messages(thread, context, exclude_roles=(FolderRole.SENT, FolderRole.DRAFTS))
            if m.from_addr not in me]
    if not msgs:
        raise ActionError("Nothing to report: every message in this conversation is from you.")
    result = {"blocked": None}
    sender = msgs[-1].from_addr
    if block == "address":
        rule = spam.add_block(BlockKind.ADDRESS, sender, note=f"Reported: {thread.subject[:200]}")
        result["blocked"] = {"kind": rule.kind, "value": rule.value}
    elif block == "domain":
        rule = spam.add_block(BlockKind.DOMAIN, spam.domain_of(sender), note=f"Reported: {thread.subject[:200]}")
        result["blocked"] = {"kind": rule.kind, "value": rule.value}
    with transaction.atomic():
        junk = role_folder(FolderRole.JUNK)
        move_messages(msgs, junk)
        set_flags(msgs, add=["$Junk"], remove=["$NotJunk"])
    return result


def not_spam(thread: Thread, context: Folder | None) -> dict:
    junk = role_folder(FolderRole.JUNK)
    msgs = context_messages(thread, junk)
    removed: list[str] = []
    for addr in {m.from_addr for m in msgs}:
        removed += spam.remove_blocks_for(addr)
    with transaction.atomic():
        move_messages(msgs, role_folder(FolderRole.INBOX))
        set_flags(msgs, add=["$NotJunk"], remove=["$Junk"])
        Message.objects.filter(pk__in=[m.pk for m in msgs]).update(routed_by_block=None)
    return {"unblocked": removed}


__all__ = ["role_folder", "set_flags", "move_messages", "delete_forever", "set_labels",
           "archive", "trash", "move_thread", "report_spam", "not_spam", "labels_mod"]
