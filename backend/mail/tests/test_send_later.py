"""Send later: schedule, list, cancel, and the worker sending on time."""

from datetime import timedelta

from django.utils import timezone

from mail.imap.fake import FakeSender
from mail.models import Draft, Message, OpStatus, OutboxOp
from mail.outbox import Executor


def _reply(api):
    m = Message.objects.get(message_id="trip2@friends.test")
    d = api.post("/api/drafts", {"mode": "reply", "inReplyTo": m.pk, "to": [{"addr": "alice@friends.test", "name": ""}],
                                 "subject": "Re: Trip planning", "bodyHtml": "<p>Later!</p>"}).json()
    return m, d


def test_schedule_list_and_send_on_time(loaded, api, server):
    m, d = _reply(api)
    at = timezone.now() + timedelta(hours=3)
    r = api.post(f"/api/drafts/{d['id']}/send", {"sendAt": at.isoformat()})
    assert r.status_code == 200 and r.json()["status"] == "scheduled"

    listed = api.get("/api/scheduled").json()
    assert [x["id"] for x in listed] == [d["id"]] and listed[0]["threadId"] == m.thread_id
    t = api.get(f"/api/threads/{m.thread_id}").json()
    assert [x["id"] for x in t["scheduled"]] == [d["id"]]
    # Can't be edited while it waits.
    assert api.patch(f"/api/drafts/{d['id']}", {"subject": "x"}).status_code == 409

    snd = FakeSender()
    ex = Executor(server, snd)
    ex.run_pending()
    assert snd.sent == []  # not yet
    OutboxOp.objects.filter(kind="send").update(not_before=timezone.now() - timedelta(seconds=1))
    ex.run_pending()
    assert len(snd.sent) == 1
    assert Draft.objects.get(pk=d["id"]).status == "sent"
    assert api.get("/api/scheduled").json() == []


def test_unschedule_returns_to_editing(loaded, api, server):
    _, d = _reply(api)
    api.post(f"/api/drafts/{d['id']}/send", {"sendAt": (timezone.now() + timedelta(days=1)).isoformat()})
    r = api.post(f"/api/drafts/{d['id']}/unschedule")
    assert r.status_code == 200 and r.json()["status"] == "editing" and r.json()["sendAt"] is None
    assert OutboxOp.objects.filter(kind="send", status=OpStatus.PENDING).count() == 0
    # A copy goes back to the server's Drafts folder.
    assert OutboxOp.objects.filter(kind="save_draft", status=OpStatus.PENDING).exists()
    snd = FakeSender()
    Executor(server, snd).run_pending()
    assert snd.sent == []
    assert api.post(f"/api/drafts/{d['id']}/unschedule").status_code == 409


def test_schedule_removes_server_draft_copy(loaded, api, server):
    _, d = _reply(api)
    api.patch(f"/api/drafts/{d['id']}", {"saveToServer": True})
    OutboxOp.objects.filter(kind="save_draft").update(not_before=None)
    Executor(server, FakeSender()).run_pending()
    assert Draft.objects.get(pk=d["id"]).server_uid
    api.post(f"/api/drafts/{d['id']}/send", {"sendAt": (timezone.now() + timedelta(hours=2)).isoformat()})
    assert Draft.objects.get(pk=d["id"]).server_uid is None
    assert OutboxOp.objects.filter(kind="delete_server_draft", status=OpStatus.PENDING).exists()


def test_bad_times_rejected(loaded, api):
    _, d = _reply(api)
    past = (timezone.now() - timedelta(minutes=5)).isoformat()
    assert api.post(f"/api/drafts/{d['id']}/send", {"sendAt": past}).status_code == 400
    assert api.post(f"/api/drafts/{d['id']}/send", {"sendAt": "next tuesday"}).status_code == 400
    assert api.post(f"/api/drafts/{d['id']}/send", {"sendAt": "2026-12-01T09:00:00"}).status_code == 400  # no zone
    far = (timezone.now() + timedelta(days=400)).isoformat()
    assert api.post(f"/api/drafts/{d['id']}/send", {"sendAt": far}).status_code == 400
    assert Draft.objects.get(pk=d["id"]).status == "editing"


def test_soon_time_is_a_normal_send(loaded, api, settings):
    settings.MAIL = {**settings.MAIL, "SEND_UNDO_SECONDS": 10}
    _, d = _reply(api)
    r = api.post(f"/api/drafts/{d['id']}/send", {"sendAt": (timezone.now() + timedelta(seconds=15)).isoformat()})
    assert r.json()["status"] == "queued"  # within the undo window: undo still works
