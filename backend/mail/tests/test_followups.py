from datetime import timedelta

import pytest
from django.utils import timezone

from mail import followups
from mail.models import ChangeEvent, Draft, FollowUp, Folder, FolderRole, Message
from mail.outbox import Executor
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def test_nudge_when_nobody_replies(loaded):
    t = Message.objects.get(message_id="trip0@manifest.test").thread
    # Alice did reply after my message, so a nudge on this thread closes itself...
    f = followups.create_for_thread(t, timezone.now() + timedelta(days=1))
    assert followups.check_due(now=timezone.now() + timedelta(days=2)) == 0
    f.refresh_from_db()
    assert f.status == "done"


def test_nudge_fires_and_reply_closes_it(loaded, engine, server, api, settings):
    settings.MAIL = {**settings.MAIL, "SEND_UNDO_SECONDS": 0}
    due = (timezone.now() + timedelta(days=3)).isoformat()
    d = api.post("/api/drafts", {"to": ["bob@friends.test"], "subject": "Any news?", "bodyHtml": "<p>Hi Bob</p>",
                                 "followupAt": due}).json()
    assert d["followupAt"]
    api.post(f"/api/drafts/{d['id']}/send")
    from mail.imap.fake import FakeSender

    ex = Executor(server, FakeSender())
    ex.run_pending()
    ex.run_pending()
    f = FollowUp.objects.get()
    assert f.status == "waiting" and f.message_key == Draft.objects.get(pk=d["id"]).message_id
    # Due, nobody replied -> nudged, with an event.
    assert followups.check_due(now=timezone.now() + timedelta(days=4)) == 1
    f.refresh_from_db()
    assert f.status == "nudged" and f.thread_id
    assert ChangeEvent.objects.filter(kind="nudge").exists()
    lst = api.get("/api/followups").json()
    assert lst[0]["status"] == "nudged" and lst[0]["subject"] == "Any news?"
    # Bob finally answers: the nudge closes.
    server.deliver("INBOX", corpus.msg(
        [("From", "Bob <bob@friends.test>"), ("To", corpus.ME), ("Subject", "Re: Any news?"),
         ("Message-ID", "<bob-re@friends.test>"), ("In-Reply-To", f"<{f.message_key}>"),
         ("Date", "Tue, 17 Nov 2026 12:00:00 +0000")], "Yes!"))
    engine.sync_folder(Folder.objects.get(role=FolderRole.INBOX))
    f.refresh_from_db()
    assert f.status == "done"


def test_followup_api_validation_and_actions(loaded, api):
    t = Message.objects.get(subject="Lunch on Friday?").thread  # I never wrote here
    r = api.post("/api/followups", {"threadId": t.pk, "until": (timezone.now() + timedelta(days=1)).isoformat()})
    assert r.status_code == 400
    mine = Message.objects.get(message_id="trip0@manifest.test").thread
    f = api.post("/api/followups", {"threadId": mine.pk, "until": (timezone.now() + timedelta(days=1)).isoformat()}).json()
    later = (timezone.now() + timedelta(days=5)).isoformat()
    assert api.post(f"/api/followups/{f['id']}", {"action": "later", "until": later}).json()["status"] == "waiting"
    assert api.post(f"/api/followups/{f['id']}", {"action": "done"}).json()["status"] == "done"
    bad = api.patch(f"/api/drafts/{api.post('/api/drafts', {}).json()['id']}", {"followupAt": "2000-01-01T00:00:00+00:00"})
    assert bad.status_code == 400


def test_sender_info(loaded, api):
    info = api.get("/api/senders", addr="alice@friends.test").json()
    assert info["received"] >= 3 and info["sent"] >= 1 and info["firstSeen"]
    assert info["domainBlockAllowed"] is True
    idn = api.get("/api/senders", addr="id@аpple.com").json()
    assert idn["domainAscii"].startswith("xn--")
