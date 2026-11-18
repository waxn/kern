"""The local copy of a user's mail across disconnects, mailbox changes,
backups and restores.

The mail server is the source of truth, so the local copy of messages is a
cache: it can always be thrown away and downloaded again. What the user made
here (snoozes, follow-ups, mutes, labels' colours, templates, block rules,
preferences, scheduled sends) is kept by Message-ID and survives a resync.
"""
from __future__ import annotations

import shutil

from django.db import transaction

from kern import secretbox, tenancy

CACHE_TABLES = [  # deleted in this order (children first)
    "mail_attachment", "mail_messagereference", "mail_message_labels", "mail_message", "mail_blob",
    "mail_thread", "mail_folder", "mail_outboxop", "mail_changeevent", "mail_workerstatus",
]


def _store_dir():
    return tenancy.data_dir() / "mail"


def clear_cache() -> None:
    """Drop the local copy of messages; the worker downloads them again."""
    from .models import (Attachment, Blob, ChangeEvent, Draft, Folder, Message, MessageReference, OutboxOp,
                         Thread, WorkerStatus)

    with transaction.atomic(using=tenancy.current_alias()):
        Draft.objects.update(server_folder=None, server_uidvalidity=None, server_uid=None)
        Attachment.objects.all().delete()
        MessageReference.objects.all().delete()
        Message.labels.through.objects.all().delete()
        Message.objects.all().delete()
        Blob.objects.all().delete()
        Thread.objects.all().delete()
        Folder.objects.all().delete()
        OutboxOp.objects.all().delete()
        ChangeEvent.objects.all().delete()
        WorkerStatus.objects.all().delete()
    shutil.rmtree(_store_dir() / "blobs", ignore_errors=True)


def forget_local_mail() -> None:
    """Disconnect with "forget", or a different mailbox: remove everything that
    belonged to the old mailbox. Preferences, templates and block rules stay."""
    from .models import Correspondent, Draft, FollowUp, Label, Mute, Shipment, Snooze

    clear_cache()
    with transaction.atomic(using=tenancy.current_alias()):
        for m in (Snooze, FollowUp, Mute, Shipment, Correspondent, Label):
            m.objects.all().delete()
        for d in Draft.objects.all():
            for up in d.uploads.all():
                up.delete()
            d.delete()
    shutil.rmtree(_store_dir(), ignore_errors=True)
    from . import account

    account.invalidate()


def after_restore() -> None:
    """A workspace backup was restored. Its messages are re-downloaded; a
    password encrypted with another server's key is dropped (re-enter it)."""
    from . import account
    from .models import MailAccount

    clear_cache()
    a = MailAccount.objects.filter(pk=1).first()
    if a and a.password_enc:
        try:
            secretbox.decrypt(a.password_enc)
        except secretbox.SecretBoxError:
            a.password_enc, a.enabled = "", False
    if a:
        a.version += 1
        a.save()
    account.invalidate()


def scrub_backup(db) -> None:
    """Called on the copy of a user's database that goes into a backup zip
    (an sqlite3 connection): messages are left out (they're on the mail
    server, and email content shouldn't spread to every backup copy)."""
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table')")}
    for t in CACHE_TABLES:
        if t in have:
            db.execute(f'DELETE FROM "{t}"')
    for t in ("mail_message_fts",):
        if t in have:
            db.execute(f"INSERT INTO {t}({t}) VALUES ('delete-all')")
    db.commit()
