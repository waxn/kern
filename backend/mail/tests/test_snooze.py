from datetime import timedelta

import pytest
from django.utils import timezone

from mail import snooze
from mail.models import ChangeEvent, Folder, FolderRole, Message, Snooze
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def inbox():
    return Folder.objects.get(role=FolderRole.INBOX)


def test_snooze_moves_out_and_wakes_unread(loaded, executor, engine, server):
    m = Message.objects.get(subject="Lunch on Friday?")
    t = m.thread
    s = snooze.snooze_thread(t, inbox(), timezone.now() + timedelta(hours=3))
    assert not Message.objects.filter(thread=t, folder=inbox()).exists()
    executor.run_pending()
    assert "Snoozed" in server.boxes and len(server.boxes["Snoozed"].msgs) == 2  # created on the server
    # Not due yet.
    assert snooze.wake_due() == 0
    # Time passes.
    assert snooze.wake_due(now=timezone.now() + timedelta(hours=4)) == 1
    s.refresh_from_db()
    assert s.status == "woken"
    back = Message.objects.filter(thread=t, folder=inbox())
    assert back.count() == 2
    newest = back.order_by("-sort_date").first()
    assert newest.seen is False
    assert ChangeEvent.objects.filter(kind="snooze_wake").exists()
    executor.run_pending()
    assert len(server.boxes["Snoozed"].msgs) == 0


def test_reply_wakes_snooze_early(loaded, executor, engine, server):
    m = Message.objects.get(message_id="trip2@friends.test")
    snooze.snooze_thread(m.thread, inbox(), timezone.now() + timedelta(days=2))
    executor.run_pending()
    reply = corpus.msg([("From", "Alice Example <alice@friends.test>"), ("To", corpus.ME),
                        ("Subject", "Re: Trip planning"), ("Message-ID", "<trip3@friends.test>"),
                        ("In-Reply-To", "<trip2@friends.test>"), ("Date", "Mon, 16 Nov 2026 10:00:00 +0000")],
                       "Flights booked?")
    server.deliver("INBOX", reply)
    engine.sync_folder(inbox())
    assert Snooze.objects.get().status == "woken"
    assert Message.objects.filter(message_id="trip2@friends.test", folder=inbox()).exists()


def test_snooze_validation(loaded):
    t = Message.objects.get(subject="Lunch on Friday?").thread
    with pytest.raises(snooze.SnoozeError):
        snooze.snooze_thread(t, inbox(), timezone.now() - timedelta(minutes=5))
    with pytest.raises(snooze.SnoozeError):
        snooze.snooze_thread(t, inbox(), None)


def test_moved_out_manually_cancels_quietly(loaded, executor):
    from mail import actions

    t = Message.objects.get(subject="Lunch on Friday?").thread
    snooze.snooze_thread(t, inbox(), timezone.now() + timedelta(hours=1))
    actions.archive(t, Folder.objects.get(role=FolderRole.SNOOZED))
    assert snooze.wake_due(now=timezone.now() + timedelta(hours=2)) == 0
    assert Snooze.objects.get().status == "cancelled"


def test_snooze_api(loaded, api):
    t = Message.objects.get(subject="Lunch on Friday?").thread
    until = (timezone.now() + timedelta(days=1)).isoformat()
    r = api.post("/api/threads/actions", {"ids": [t.pk], "action": "snooze", "until": until, "context": inbox().pk})
    assert r.status_code == 200 and r.json()["until"]
    snoozed = Folder.objects.get(role=FolderRole.SNOOZED)
    lst = api.get("/api/threads", view=f"folder:{snoozed.pk}").json()["threads"]
    assert lst[0]["id"] == t.pk and lst[0]["snoozeUntil"]
    assert len(api.get("/api/snoozes").json()) == 1
    bad = api.post("/api/threads/actions", {"ids": [t.pk], "action": "snooze", "until": "yesterday"})
    assert bad.status_code == 400
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "unsnooze"})
    assert Message.objects.filter(thread=t, folder=inbox()).count() == 2
