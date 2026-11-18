"""The whole worker loop on a real thread, against the wire-protocol server:
IDLE push -> ingest, UI action -> write-back, snooze -> wake."""

import threading
import time
from datetime import timedelta

import pytest
from django.db import close_old_connections
from django.utils import timezone

from mail import actions, snooze
from mail.imap.client import ImapClient
from mail.imap.fake import FakeMailServer, FakeSender
from mail.models import Folder, FolderRole, Message, Snooze, WorkerStatus
from mail.testing import corpus
from mail.testing.imapd import IMAPTestServer
from mail.worker import Worker

pytestmark = pytest.mark.django_db(transaction=True)


def wait_for(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        close_old_connections()
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_worker_end_to_end(settings):
    settings.MAIL = {**settings.MAIL, "POLL_SECONDS": 3600}
    mail = FakeMailServer()
    mail.deliver("INBOX", corpus.simple(1, "Alice <alice@friends.test>", "Hello", "first"))
    srv = IMAPTestServer(mail).start()

    def connect():
        return ImapClient("127.0.0.1", srv.port, "me@manifest.test", "secret", use_tls=False, timeout=10)

    worker = Worker(connect, FakeSender())
    t = threading.Thread(target=worker.run_forever, daemon=True)
    t.start()
    try:
        # 1. Initial sync.
        assert wait_for(lambda: Message.objects.filter(subject="Hello").exists()), "initial sync"
        assert wait_for(lambda: WorkerStatus.objects.filter(pk=1, state="idle").exists()), "idle status"

        # 2. New mail pushed via IDLE (poll interval is an hour, so only IDLE can find it).
        assert wait_for(lambda: srv.idlers), "IDLE watcher connected"
        mail.deliver("INBOX", corpus.simple(2, "Bob <bob@friends.test>", "Pushed", "via idle"))
        srv.notify_new("INBOX")
        assert wait_for(lambda: Message.objects.filter(subject="Pushed").exists()), "IDLE push ingested"

        # 3. A UI action is written back by the loop.
        m = Message.objects.get(subject="Hello")
        actions.archive(m.thread, Folder.objects.get(role=FolderRole.INBOX))
        assert wait_for(lambda: len(mail.boxes["Archive"].msgs) == 1), "archive written back"

        # 4. A snooze wakes by itself.
        p = Message.objects.get(subject="Pushed")
        s = snooze.snooze_thread(p.thread, Folder.objects.get(role=FolderRole.INBOX), timezone.now() + timedelta(minutes=5))
        assert wait_for(lambda: len(mail.boxes.get("Snoozed").msgs) == 1 if "Snoozed" in mail.boxes else False), "snoozed on server"
        Snooze.objects.filter(pk=s.pk).update(wake_at=timezone.now() - timedelta(seconds=1))
        assert wait_for(lambda: Snooze.objects.get(pk=s.pk).status == "woken"), "snooze woke"
        assert wait_for(lambda: any(b"Pushed" in x.raw for x in mail.boxes["INBOX"].msgs.values())), "back in INBOX on server"
    finally:
        worker.stop.set()
        worker.wake.set()
        t.join(10)
        srv.stop()
    assert not t.is_alive()
