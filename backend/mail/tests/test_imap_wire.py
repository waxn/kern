"""The real imaplib-based client against a wire-protocol IMAP server."""

import threading
import time

import pytest

from mail import actions
from mail.imap.base import ServerError
from mail.imap.client import ImapClient
from mail.imap.fake import FakeMailServer
from mail.models import Folder, FolderRole, Message
from mail.outbox import Executor
from mail.sync import SyncEngine
from mail.testing import corpus
from mail.testing.imapd import IMAPTestServer


@pytest.fixture
def imapd():
    mail = FakeMailServer(folders=("INBOX", "Sent", "Junk", "Trash", "Archive", "Entwürfe"))
    srv = IMAPTestServer(mail).start()
    yield srv
    srv.stop()


def client(srv, password="secret"):
    return ImapClient("127.0.0.1", srv.port, "me@manifest.test", password, use_tls=False, timeout=10)


def test_login_and_capabilities(imapd):
    c = client(imapd)
    assert {"UIDPLUS", "MOVE", "IDLE", "CONDSTORE"} <= c.capabilities
    c.close()
    with pytest.raises(ServerError):
        client(imapd, password="wrong")


def test_folders_select_search_fetch(imapd):
    for item in list(corpus.build())[:12]:
        imapd.mail.deliver("INBOX", item.raw, ["\\Seen"] if "plain" in item.name else [])
    c = client(imapd)
    names = {f.name for f in c.list_folders()}
    assert {"INBOX", "Archive", "Entwürfe"} <= names  # modified UTF-7 round trip
    info = c.select("INBOX")
    assert info.uidvalidity == imapd.mail.boxes["INBOX"].uidvalidity and info.exists == 12
    uids = c.search_uids()
    assert uids == sorted(imapd.mail.boxes["INBOX"].msgs)
    fetched = c.fetch_full(uids[:5])
    assert [f.uid for f in fetched] == uids[:5]
    assert fetched[0].raw == imapd.mail.boxes["INBOX"].msgs[uids[0]].raw  # literal intact, byte for byte
    assert fetched[0].internal_date is not None
    flags = c.fetch_flags(uids)
    assert "\\Seen" in flags[uids[0]]
    c.close()


def test_store_move_expunge_append(imapd):
    a = imapd.mail.deliver("INBOX", corpus.simple(1, "A <a@x.test>", "one", "1"))
    b = imapd.mail.deliver("INBOX", corpus.simple(2, "B <b@x.test>", "two", "2"))
    c = client(imapd)
    c.select("INBOX", readonly=False)
    c.store_flags([a], ["\\Flagged", "$Junk"], [])
    assert {"\\Flagged", "$Junk"} <= imapd.mail.flags_of("INBOX", a)
    c.store_flags([a], [], ["$Junk"])
    assert "$Junk" not in imapd.mail.flags_of("INBOX", a)
    validity, mapping = c.move([a], "Archive")
    assert validity == imapd.mail.boxes["Archive"].uidvalidity
    assert mapping[a] in imapd.mail.boxes["Archive"].msgs and a not in imapd.mail.boxes["INBOX"].msgs
    c.store_flags([b], ["\\Deleted"], [])
    c.expunge_uids([b])
    assert b not in imapd.mail.boxes["INBOX"].msgs
    uid = c.append("Sent", corpus.simple(3, "Me <me@manifest.test>", "sent", "3"), ["\\Seen"])
    assert uid in imapd.mail.boxes["Sent"].msgs
    assert imapd.mail.flags_of("Sent", uid) == {"\\Seen"}
    c.create_folder("Projects/Ärenden")
    assert "Projects/Ärenden" in imapd.mail.boxes
    c.close()


def test_changedsince_returns_only_changes(imapd):
    a = imapd.mail.deliver("INBOX", corpus.simple(1, "A <a@x.test>", "one", "1"))
    b = imapd.mail.deliver("INBOX", corpus.simple(2, "B <b@x.test>", "two", "2"))
    c = client(imapd)
    info = c.select("INBOX")
    imapd.mail.select("INBOX")
    imapd.mail.store_flags([b], ["\\Seen"], [])
    changes = c.fetch_flags(None, changedsince=info.highestmodseq)
    assert set(changes) == {b} and a not in changes
    c.close()


def test_idle_wakes_on_new_mail(imapd):
    c = client(imapd)
    c.select("INBOX")
    result = {}

    def wait():
        result["woke"] = c.idle_wait(5)

    t = threading.Thread(target=wait)
    t.start()
    for _ in range(50):
        if imapd.idlers:
            break
        time.sleep(0.05)
    imapd.mail.deliver("INBOX", corpus.simple(9, "N <n@x.test>", "new", "hi"))
    imapd.notify_new("INBOX")
    t.join(6)
    assert result.get("woke") is True
    c.select("INBOX")  # connection still usable after IDLE
    c.close()


@pytest.mark.django_db
def test_full_sync_and_write_back_over_the_wire(imapd):
    for item in corpus.build():
        if item.folder in imapd.mail.boxes:
            imapd.mail.deliver(item.folder, item.raw, item.flags)
    c = client(imapd)
    engine = SyncEngine(c)
    engine.sync_all()
    expected = sum(len(b.msgs) for b in imapd.mail.boxes.values())
    assert Message.objects.count() == expected
    huge = Message.objects.filter(message_id__startswith="huge").values("thread_id").distinct().count()
    assert huge == 1
    m = Message.objects.get(subject="Lunch on Friday?")
    actions.archive(m.thread, Folder.objects.get(role=FolderRole.INBOX))
    actions.set_flags([m], add=["\\Flagged"])
    Executor(c).run_pending()
    m.refresh_from_db()
    assert m.server_folder.role == FolderRole.ARCHIVE and m.uid in imapd.mail.boxes["Archive"].msgs
    assert "\\Flagged" in imapd.mail.flags_of("Archive", m.uid)
    engine.sync_all()
    assert Message.objects.count() == expected  # nothing duplicated or lost
    c.close()
