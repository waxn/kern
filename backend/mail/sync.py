"""Server -> local synchronization for one folder at a time."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import events, outbox
from .imap.base import MailServer, ServerError, detect_role
from .ingest import apply_flags, ingest_raw
from .models import Folder, Message
from .threads import refresh_thread
from .account import cfg as _mail_cfg

log = logging.getLogger("kern.mail.sync")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


MAX_INGEST_FAILURES = 3


class SyncEngine:
    def __init__(self, server: MailServer):
        self.server = server
        # (folder id, uidvalidity, uid) -> failed ingest attempts, so one
        # unparseable message isn't downloaded again on every sync.
        self.failures: dict[tuple[int, int, int], int] = {}

    # -- folders --------------------------------------------------------
    def sync_folder_list(self) -> list[Folder]:
        infos = self.server.list_folders()
        seen = set()
        for info in infos:
            role = detect_role(info)
            folder, created = Folder.objects.get_or_create(
                name=info.name,
                defaults={"delimiter": info.delimiter or "", "role": role, "selectable": info.selectable},
            )
            seen.add(folder.pk)
            changed = []
            if not created:
                if folder.selectable != info.selectable:
                    folder.selectable = info.selectable
                    changed.append("selectable")
                if not folder.exists_on_server or folder.needs_create:
                    folder.exists_on_server, folder.needs_create = True, False
                    changed += ["exists_on_server", "needs_create"]
                if role and folder.role != role and not Folder.objects.filter(role=role).exclude(pk=folder.pk).exists():
                    folder.role = role
                    changed.append("role")
            if changed:
                folder.save(update_fields=changed)
        # Folders gone from the server (and not waiting to be created there).
        gone = Folder.objects.exclude(pk__in=seen).filter(needs_create=False)
        for folder in gone:
            log.info("folder %s disappeared from server", folder.name)
            thread_ids = set(Message.objects.filter(server_folder=folder).values_list("thread_id", flat=True))
            folder.delete()
            for tid in thread_ids:
                refresh_thread(tid)
        return list(Folder.objects.filter(selectable=True, exists_on_server=True))

    # -- one folder -----------------------------------------------------
    def sync_folder(self, folder: Folder, *, full_flags: bool = True) -> dict:
        stats = {"new": 0, "gone": 0, "flags": 0}
        info = self.server.select(folder.name, readonly=True)

        if folder.uidvalidity and info.uidvalidity != folder.uidvalidity:
            log.warning("UIDVALIDITY changed for %s; reloading folder", folder.name)
            with transaction.atomic():
                thread_ids = set(Message.objects.filter(server_folder=folder).values_list("thread_id", flat=True))
                Message.objects.filter(server_folder=folder).delete()
                for tid in thread_ids:
                    refresh_thread(tid)
            folder.highestmodseq = None
            folder.initial_sync_done = False
        if folder.uidvalidity != info.uidvalidity:
            # Record it now, so an interrupted first sync still notices a
            # later UIDVALIDITY change.
            folder.uidvalidity = info.uidvalidity
            folder.save(update_fields=["uidvalidity", "highestmodseq", "initial_sync_done"])

        initial = not folder.initial_sync_done
        server_uids = set(self.server.search_uids())
        local = dict(
            Message.objects.filter(server_folder=folder, uidvalidity=info.uidvalidity, uid__isnull=False)
            .values_list("uid", "id")
        )
        busy = outbox.pending_message_ids()

        # Expunged on the server (or moved away by another client).
        gone_ids = [mid for uid, mid in local.items() if uid not in server_uids and mid not in busy]
        if gone_ids:
            thread_ids = set(Message.objects.filter(pk__in=gone_ids).values_list("thread_id", flat=True))
            Message.objects.filter(pk__in=gone_ids).delete()
            for tid in thread_ids:
                refresh_thread(tid)
            stats["gone"] = len(gone_ids)
            events.emit("update", threads=sorted(t for t in thread_ids if t))

        # New messages, newest first so recent mail appears quickly.
        new = sorted(
            (u for u in server_uids - set(local)
             if self.failures.get((folder.pk, info.uidvalidity, u), 0) < MAX_INGEST_FAILURES),
            reverse=True,
        )
        batch_size = _mail_cfg()["FETCH_BATCH"]
        for batch in chunks(new, batch_size):
            # Cheap flags-only fetch first: never download the body of a
            # message another client already marked \Deleted.
            flags = self.server.fetch_flags(batch)
            wanted = [u for u in batch if not any(f.lower() == "\\deleted" for f in flags.get(u, []))]
            to_refresh: set = set()
            for fetched in self.server.fetch_full(wanted) if wanted else []:
                try:
                    ingest_raw(folder, fetched.uid, info.uidvalidity, fetched.flags,
                               fetched.internal_date, fetched.raw, initial=initial, refresh=to_refresh)
                    stats["new"] += 1
                except Exception:
                    key = (folder.pk, info.uidvalidity, fetched.uid)
                    self.failures[key] = self.failures.get(key, 0) + 1
                    log.exception("failed to ingest uid %s in %s (attempt %s)", fetched.uid, folder.name,
                                  self.failures[key])
            for tid in to_refresh:
                refresh_thread(tid)
            if initial:
                events.emit("sync_progress", folder=folder.pk, done=stats["new"], total=len(new))

        # Flag changes made by other clients.
        if local and full_flags:
            if folder.highestmodseq and info.highestmodseq and "CONDSTORE" in self.server.capabilities:
                if info.highestmodseq != folder.highestmodseq:
                    changes = self.server.fetch_flags(None, changedsince=folder.highestmodseq)
                else:
                    changes = {}
            else:
                changes = {}
                for batch in chunks(sorted(local), 2000):
                    changes.update(self.server.fetch_flags(batch))
            touched = set()
            for uid, flags in changes.items():
                mid = local.get(uid)
                if mid is None or mid in busy:
                    continue
                m = Message.objects.filter(pk=mid).first()
                if m is None:
                    continue
                if any(f.lower() == "\\deleted" for f in flags):
                    touched.add(m.thread_id)
                    m.delete()
                    continue
                if apply_flags(m, flags):
                    stats["flags"] += 1
                    touched.add(m.thread_id)
            for tid in touched:
                refresh_thread(tid)
            if touched:
                events.emit("update", threads=sorted(t for t in touched if t))

        folder.uidvalidity = info.uidvalidity
        folder.uidnext = info.uidnext
        folder.highestmodseq = info.highestmodseq
        folder.initial_sync_done = True
        folder.last_sync = timezone.now()
        folder.save(update_fields=["uidvalidity", "uidnext", "highestmodseq", "initial_sync_done", "last_sync"])
        if stats["new"] and initial:
            events.emit("folder_synced", folder=folder.pk)
        return stats

    def sync_all(self) -> None:
        folders = self.sync_folder_list()
        # Inbox first, then the rest.
        folders.sort(key=lambda f: (f.role != "inbox", f.role == "", f.name))
        for folder in folders:
            try:
                self.sync_folder(folder)
            except ServerError as exc:
                log.warning("sync of %s failed: %s", folder.name, exc)
