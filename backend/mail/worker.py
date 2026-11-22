"""The sync worker: keeps the local copy in step with the server and runs
the write-back queue. Runs as its own process next to the web server."""

from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import events, outbox
from .imap.base import MailSender, MailServer, ServerError
from .models import Folder, FolderRole, WorkerStatus
from .sync import SyncEngine
from .account import cfg as _mail_cfg

log = logging.getLogger("kern.mail.worker")
IDLE_SECONDS = 25 * 60  # re-issue IDLE before the 29-minute server timeout


_last_status: dict = {}  # per user: {"key", "at"}


def set_status(state: str, detail: str = "", error: str | None = None) -> None:
    from kern import tenancy

    key = (state, detail)
    now = time.monotonic()
    last = _last_status.setdefault(tenancy.current_uid(), {"key": None, "at": 0.0})
    if error is None and last["key"] == key and now - last["at"] < 15:
        return  # unchanged; heartbeat every 15s is enough
    last.update(key=key, at=now)
    ws, _ = WorkerStatus.objects.get_or_create(pk=1)
    ws.state, ws.detail, ws.heartbeat = state, detail[:500], timezone.now()
    fields = ["state", "detail", "heartbeat"]
    if error is not None:
        ws.last_error, ws.last_error_at = error[:2000], timezone.now()
        fields += ["last_error", "last_error_at"]
    ws.save(update_fields=fields)


class IdleWatcher(threading.Thread):
    """Holds a second IMAP connection in IDLE on INBOX and sets `event`
    whenever the server reports a change."""

    def __init__(self, connect, event: threading.Event, stop: threading.Event):
        super().__init__(daemon=True, name="imap-idle")
        self.connect, self.event, self.stop = connect, event, stop
        self.server = None  # closed by Worker.shutdown() to end a blocking IDLE at once

    def run(self):
        backoff = 5
        while not self.stop.is_set():
            server = None
            try:
                server = self.connect()
                self.server = server
                if self.stop.is_set():
                    break
                server.select("INBOX", readonly=True)
                backoff = 5
                while not self.stop.is_set():
                    if server.idle_wait(IDLE_SECONDS):
                        self.event.set()
            except Exception as exc:  # noqa: BLE001 - reconnect on anything
                log.warning("IDLE connection problem: %s", exc)
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 300)
            finally:
                self.server = None
                if server is not None:
                    server.close()


class Worker:
    def __init__(self, connect, sender: MailSender | None, use_idle: bool = True, require_config: bool = True):
        self.connect = connect
        self.require_config = require_config
        self.use_idle = use_idle
        self.sender = sender
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.idle: IdleWatcher | None = None

    def shutdown(self) -> None:
        """Stop soon (from another thread): ends the loop and any IDLE wait."""
        self.stop.set()
        self.wake.set()
        idle = self.idle
        if idle is not None and idle.server is not None:
            try:
                idle.server.close()
            except Exception:  # noqa: BLE001
                pass

    def run_forever(self):
        if self.require_config and not _mail_cfg()["USERNAME"]:
            log.error("MAIL_USERNAME not set; worker idle. See .env.example.")
            while not self.stop.is_set():
                set_status("unconfigured", "MAIL_USERNAME is not set")
                self.stop.wait(60)
            return
        if self.use_idle:
            self.idle = IdleWatcher(self.connect, self.wake, self.stop)
            self.idle.start()
        backoff = 5
        while not self.stop.is_set():
            server: MailServer | None = None
            try:
                set_status("connecting")
                server = self.connect()
                WorkerStatus.objects.filter(pk=1).update(capabilities=sorted(server.capabilities))
                backoff = 5
                self.loop(server)
            except (ServerError, OSError) as exc:
                log.warning("worker connection error: %s", exc)
                set_status("error", "Connection problem; retrying", error=str(exc))
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 300)
            except Exception as exc:  # noqa: BLE001
                log.exception("worker crashed")
                set_status("error", "Unexpected error; retrying", error=repr(exc))
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 300)
            finally:
                if server is not None:
                    server.close()
                close_old_connections()

    def sync_pushed(self, engine: SyncEngine) -> None:
        """IDLE saw a change in INBOX: fetch it now (new mail first)."""
        if not self.wake.is_set():
            return
        self.wake.clear()
        inbox = Folder.objects.filter(role=FolderRole.INBOX).first()
        if inbox:
            engine.sync_folder(inbox)

    def loop(self, server: MailServer):
        engine = SyncEngine(server)
        executor = outbox.Executor(server, self.sender)
        set_status("syncing", "Initial sync")
        engine.sync_all()
        last_full = time.monotonic()
        last_prune = 0.0
        last_tracking = 0.0
        while not self.stop.is_set():
            close_old_connections()
            # 1. Write-back queue.
            if outbox.has_pending():
                set_status("working", "Saving changes")
                executor.run_pending()
                for fid in sorted(executor.touched_folders):
                    folder = Folder.objects.filter(pk=fid, selectable=True, exists_on_server=True).first()
                    if folder:
                        engine.sync_folder(folder)
                executor.touched_folders.clear()
                if executor.checked:
                    executor.checked = False
                    events.emit("checked")
            # 2. Snoozed conversations whose time has come.
            from . import snooze

            if snooze.wake_due():
                continue  # run the resulting moves right away
            from . import followups

            followups.check_due()
            # Live package tracking (opt-in; rate-limited per package inside).
            if time.monotonic() - last_tracking > 120:
                from . import tracking

                tracking.refresh()
                last_tracking = time.monotonic()
            # 3. Push from IDLE: sync INBOX quickly.
            self.sync_pushed(engine)
            # 4. Periodic full sweep (other folders, flags changed elsewhere).
            if time.monotonic() - last_full > _mail_cfg()["POLL_SECONDS"]:
                set_status("syncing", "Checking folders")
                engine.sync_all(between=lambda: self.sync_pushed(engine))
                last_full = time.monotonic()
            if time.monotonic() - last_prune > 3600:
                events.prune()
                last_prune = time.monotonic()
            set_status("idle", "Up to date")
            self.wake.wait(1.0)
