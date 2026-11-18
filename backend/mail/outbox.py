"""Write-back queue: local changes -> IMAP/SMTP.

SECURITY/DATA (review carefully): this is the only code that changes or
deletes mail on your server.

* The UI changes local rows immediately and enqueues an op here. The sync
  worker runs ops in order, one at a time.
* Ops name messages by database id and resolve their *current* server
  location (server_folder, uidvalidity, uid) when they run. If the UIDVALIDITY
  no longer matches, the op does nothing to that message (the mailbox was
  recreated; touching UIDs blindly could hit the wrong mail).
* Permanent deletion (expunge) only ever uses UID EXPUNGE on the exact UIDs
  recorded when you clicked delete. Without the UIDPLUS extension it refuses,
  because a plain EXPUNGE would also remove unrelated messages that another
  client flagged \\Deleted.
* Sending is split from saving to Sent so a failure after SMTP accepted the
  message never sends it twice.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import events, store
from .imap.base import MailSender, MailServer, ServerError
from .models import Draft, DraftStatus, Folder, Message, OpStatus, OutboxOp

log = logging.getLogger("kern.mail.outbox")
MAX_ATTEMPTS = 8
MAX_DEFERS = 120


class Defer(Exception):
    """Not ready yet (e.g. waiting for a moved message's new UID)."""


def enqueue(kind: str, *, delay: float = 0, **payload) -> OutboxOp:
    not_before = timezone.now() + timedelta(seconds=delay) if delay else None
    return OutboxOp.objects.create(kind=kind, payload=payload, not_before=not_before)


def pending_message_ids() -> set[int]:
    ids: set[int] = set()
    for p in OutboxOp.objects.filter(status=OpStatus.PENDING).values_list("payload", flat=True):
        ids.update(p.get("message_ids", []))
    return ids


def has_pending() -> bool:
    now = timezone.now()
    return OutboxOp.objects.filter(status=OpStatus.PENDING).exclude(not_before__gt=now).exists()


class Executor:
    def __init__(self, server: MailServer, sender: MailSender | None = None):
        self.server = server
        self.sender = sender
        self.touched_folders: set[int] = set()

    # -- driver ---------------------------------------------------------
    def run_pending(self, limit: int = 200) -> int:
        now = timezone.now()
        ops = list(
            OutboxOp.objects.filter(status=OpStatus.PENDING)
            .exclude(not_before__gt=now)
            .order_by("id")[:limit]
        )
        blocked: set[int] = set()
        done = 0
        for op in ops:
            ids = set(op.payload.get("message_ids", []))
            if ids & blocked:
                continue
            try:
                getattr(self, f"op_{op.kind}")(op)
            except Defer as d:
                blocked |= ids
                op.attempts += 1
                if op.attempts > MAX_DEFERS:
                    self._fail(op, f"gave up waiting: {d}")
                else:
                    op.not_before = timezone.now() + timedelta(seconds=3)
                    op.save(update_fields=["attempts", "not_before"])
                continue
            except (ServerError, OSError, ValueError) as exc:
                blocked |= ids
                op.attempts += 1
                op.last_error = f"{exc.__class__.__name__}: {exc}"[:2000]
                if op.attempts >= MAX_ATTEMPTS:
                    self._fail(op, op.last_error)
                else:
                    op.not_before = timezone.now() + timedelta(seconds=min(600, 2 ** op.attempts))
                    op.save(update_fields=["attempts", "last_error", "not_before"])
                log.warning("op %s %s failed (attempt %s): %s", op.pk, op.kind, op.attempts, exc)
                if isinstance(exc, OSError):
                    raise  # connection trouble: let the worker reconnect
                continue
            op.status = OpStatus.DONE
            op.finished = timezone.now()
            op.save(update_fields=["status", "finished"])
            done += 1
        return done

    def _fail(self, op: OutboxOp, error: str) -> None:
        op.status = OpStatus.FAILED
        op.last_error = error[:2000]
        op.finished = timezone.now()
        op.save(update_fields=["status", "last_error", "finished"])
        revert = getattr(self, f"revert_{op.kind}", None)
        if revert:
            try:
                revert(op)
            except Exception:
                log.exception("revert of op %s failed", op.pk)
        events.emit("op_failed", op=op.kind, error=error[:300])

    # -- helpers --------------------------------------------------------
    def _select(self, folder: Folder, readonly: bool = False):
        info = self.server.select(folder.name, readonly=readonly)
        return info

    def _grouped(self, message_ids: list[int]):
        """Group messages by server folder; Defer if any is still waiting for
        its UID."""
        msgs = list(Message.objects.filter(pk__in=message_ids).select_related("server_folder"))
        groups: dict[int, list[Message]] = {}
        for m in msgs:
            if m.uid is None:
                raise Defer(f"message {m.pk} has no UID yet")
            groups.setdefault(m.server_folder_id, []).append(m)
        return groups

    def _ensure_folder(self, folder: Folder) -> None:
        if folder.needs_create:
            try:
                self.server.create_folder(folder.name)
            except ServerError as exc:
                if "exist" not in str(exc).lower():
                    raise
            folder.needs_create = False
            folder.exists_on_server = True
            folder.save(update_fields=["needs_create", "exists_on_server"])

    # -- ops ------------------------------------------------------------
    def op_create_folder(self, op):
        folder = Folder.objects.filter(pk=op.payload["folder"]).first()
        if folder:
            self._ensure_folder(folder)

    def op_flags(self, op):
        add, remove = op.payload.get("add", []), op.payload.get("remove", [])
        for folder_id, msgs in self._grouped(op.payload["message_ids"]).items():
            folder = msgs[0].server_folder
            info = self._select(folder)
            uids = [m.uid for m in msgs if m.uidvalidity == info.uidvalidity]
            if uids:
                self.server.store_flags(uids, add, remove)
            self.touched_folders.add(folder_id)

    def op_move(self, op):
        dest = Folder.objects.get(pk=op.payload["dest"])
        self._ensure_folder(dest)
        for folder_id, msgs in self._grouped(op.payload["message_ids"]).items():
            if folder_id == dest.pk:
                continue
            folder = msgs[0].server_folder
            info = self._select(folder)
            valid = [m for m in msgs if m.uidvalidity == info.uidvalidity]
            if not valid:
                continue
            copy_validity, mapping = self.server.move([m.uid for m in valid], dest.name)
            dest_validity = copy_validity or dest.uidvalidity
            with transaction.atomic():
                for m in valid:
                    m.server_folder = dest
                    new_uid = mapping.get(m.uid)
                    if new_uid and dest_validity:
                        m.uid, m.uidvalidity = new_uid, dest_validity
                    else:
                        m.uid, m.uidvalidity = None, None  # reconciled by next sync of dest
                    m.save(update_fields=["server_folder", "uid", "uidvalidity", "updated"])
            self.touched_folders.update({folder_id, dest.pk})

    def revert_move(self, op):
        # Show messages where they really are again.
        for m in Message.objects.filter(pk__in=op.payload["message_ids"]):
            if m.folder_id != m.server_folder_id:
                m.folder_id = m.server_folder_id
                m.save(update_fields=["folder", "updated"])
                from .threads import refresh_thread

                refresh_thread(m.thread_id)

    def op_expunge(self, op):
        if "UIDPLUS" not in self.server.capabilities:
            raise ValueError("server lacks UIDPLUS; refusing to EXPUNGE (would remove other mail)")
        by_folder: dict[int, list[tuple[int, int]]] = {}
        for folder_id, validity, uid in op.payload["locations"]:
            by_folder.setdefault(folder_id, []).append((validity, uid))
        for folder_id, locs in by_folder.items():
            folder = Folder.objects.filter(pk=folder_id).first()
            if folder is None:
                continue
            info = self._select(folder)
            uids = [uid for validity, uid in locs if validity == info.uidvalidity]
            if uids:
                self.server.store_flags(uids, ["\\Deleted"], [])
                self.server.expunge_uids(uids)
            self.touched_folders.add(folder_id)

    def op_append(self, op):
        folder = Folder.objects.get(pk=op.payload["folder"])
        self._ensure_folder(folder)
        raw = store.get(op.payload["blob"])
        uid = self.server.append(folder.name, raw, op.payload.get("flags", []))
        if uid:
            info = self._select(folder, readonly=True)
            from .ingest import ingest_raw

            if not Message.objects.filter(server_folder=folder, uidvalidity=info.uidvalidity, uid=uid).exists():
                ingest_raw(folder, uid, info.uidvalidity, op.payload.get("flags", []), timezone.now(), raw)
        self.touched_folders.add(folder.pk)

    def op_send(self, op):
        from . import sending

        draft = Draft.objects.filter(pk=op.payload["draft"]).first()
        if draft is None or draft.status not in (DraftStatus.QUEUED, DraftStatus.SCHEDULED):
            return  # cancelled (undo) or already handled
        was_scheduled = draft.status == DraftStatus.SCHEDULED
        if self.sender is None:
            raise ServerError("no SMTP sender configured")
        draft.status = DraftStatus.SENDING
        draft.save(update_fields=["status"])
        try:
            raw, envelope_from, rcpts = sending.build_for_send(draft)
            refused = self.sender.send(envelope_from, rcpts, raw) or {}
        except Exception as exc:
            draft.status = DraftStatus.QUEUED if op.attempts + 1 < MAX_ATTEMPTS else DraftStatus.FAILED
            draft.error = str(exc)[:1000]
            draft.save(update_fields=["status", "error"])
            events.emit("draft", draft=draft.pk, status=draft.status)
            raise ServerError(f"SMTP: {exc}") from exc
        if refused:
            draft.error = "Not delivered to: " + ", ".join(f"{k} ({v[0]})" for k, v in refused.items())
            draft.save(update_fields=["error"])
        sending.after_send(draft, raw)
        events.emit("draft", draft=draft.pk, status="sent", scheduled=was_scheduled)

    def revert_send(self, op):
        Draft.objects.filter(pk=op.payload["draft"]).update(status=DraftStatus.FAILED)

    def op_save_draft(self, op):
        from . import sending

        draft = Draft.objects.filter(pk=op.payload["draft"]).first()
        if draft is None or draft.status != DraftStatus.EDITING:
            return
        folder = sending.drafts_folder()
        self._ensure_folder(folder)
        raw = sending.build_mime(draft, for_draft=True)
        new_uid = self.server.append(folder.name, raw, ["\\Draft", "\\Seen"])
        info = self._select(folder)
        old = (draft.server_folder_id, draft.server_uidvalidity, draft.server_uid)
        if old[2] and old[0] == folder.pk and old[1] == info.uidvalidity:
            self.server.store_flags([old[2]], ["\\Deleted"], [])
            if "UIDPLUS" in self.server.capabilities:
                self.server.expunge_uids([old[2]])
        Draft.objects.filter(pk=draft.pk).update(
            server_folder=folder, server_uidvalidity=info.uidvalidity, server_uid=new_uid
        )
        self.touched_folders.add(folder.pk)

    def op_delete_server_draft(self, op):
        folder = Folder.objects.filter(pk=op.payload["folder"]).first()
        if not folder:
            return
        info = self._select(folder)
        if info.uidvalidity == op.payload["uidvalidity"]:
            self.server.store_flags([op.payload["uid"]], ["\\Deleted"], [])
            if "UIDPLUS" in self.server.capabilities:
                self.server.expunge_uids([op.payload["uid"]])
        self.touched_folders.add(folder.pk)
