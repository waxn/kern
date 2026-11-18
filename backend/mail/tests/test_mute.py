import pytest

from mail.models import Folder, FolderRole, Message
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def inbox():
    return Folder.objects.get(role=FolderRole.INBOX)


def reply(n, irt):
    return corpus.msg([("From", "Alice Example <alice@friends.test>"), ("To", corpus.ME), ("Subject", "Re: Trip planning"),
                       ("Message-ID", f"<trip-r{n}@friends.test>"), ("In-Reply-To", irt),
                       ("Date", "Mon, 16 Nov 2026 10:00:00 +0000")], f"reply {n}")


def test_muted_conversation_skips_the_inbox(loaded, api, engine, server, executor):
    t = Message.objects.get(message_id="trip2@friends.test").thread
    r = api.post("/api/threads/actions", {"ids": [t.pk], "action": "mute", "context": inbox().pk})
    assert r.status_code == 200
    assert not Message.objects.filter(thread=t, folder__role=FolderRole.INBOX).exists()
    executor.run_pending()
    server.deliver("INBOX", reply(1, "<trip2@friends.test>"))
    engine.sync_folder(inbox())
    new = Message.objects.get(message_id="trip-r1@friends.test")
    assert new.folder.role == FolderRole.ARCHIVE and new.seen
    listed = api.get("/api/threads", view="all").json()["threads"]
    assert next(x for x in listed if x["id"] == new.thread_id)["muted"] is True
    # Unmute: the next reply lands in the Inbox again.
    api.post("/api/threads/actions", {"ids": [new.thread_id], "action": "unmute"})
    executor.run_pending()
    server.deliver("INBOX", reply(2, "<trip-r1@friends.test>"))
    engine.sync_folder(inbox())
    assert Message.objects.get(message_id="trip-r2@friends.test").folder.role == FolderRole.INBOX


def test_undo_mute_restores_inbox(loaded, api):
    t = Message.objects.get(message_id="trip2@friends.test").thread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "mute", "context": inbox().pk})
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "unmute", "dest": inbox().pk})
    assert Message.objects.filter(thread=t, folder__role=FolderRole.INBOX).count() == 2


def test_other_conversations_unaffected(loaded, api, engine, server):
    t = Message.objects.get(message_id="trip2@friends.test").thread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "mute"})
    server.deliver("INBOX", corpus.simple(900, "Bob <bob@friends.test>", "Unrelated", "hi"))
    engine.sync_folder(inbox())
    assert Message.objects.get(subject="Unrelated").folder.role == FolderRole.INBOX
