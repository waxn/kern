"""Mail ⇄ Kern tasks."""
import datetime as dt

from django.utils import timezone

from mail.models import Draft, FollowUp, Message, Thread
from notes.models import Task


def _thread(subject="Re: Re: Trip planning"):
    return Message.objects.filter(subject=subject).first().thread


def test_task_from_thread_links_back(loaded, api):
    t = _thread()
    r = api.post(f"/api/threads/{t.id}/task", {"due": "2026-12-01", "priority": 2})
    assert r.status_code == 200, r.content
    task = r.json()
    assert task["title"] == t.subject and task["due"] == "2026-12-01" and task["priority"] == 2
    assert task["source"]["kind"] == "mail" and task["source"]["key"]
    assert "From Alice" in Task.objects.get(id=task["id"]).description
    # The conversation lists its task, and the task finds its conversation again.
    assert [x["id"] for x in api.get(f"/api/threads/{t.id}").json()["tasks"]] == [task["id"]]
    assert api.get("/api/open", key=task["source"]["key"]).json()["threadId"] == t.id
    assert api.get("/api/open", key="nope@nowhere").status_code == 404
    # Kern's own task list has it.
    assert task["id"] in {x["id"] for x in api.get("/api/tasks", view="open").json()}


def _followup(api, t):
    until = (timezone.now() + dt.timedelta(days=3)).isoformat()
    r = api.post("/api/followups", {"threadId": t.id, "until": until})
    assert r.status_code == 200, r.content
    return FollowUp.objects.get(pk=r.json()["id"])


def test_nudge_creates_task_and_reply_completes_it(loaded, api, server, engine):
    t = _thread()
    f = _followup(api, t)
    task = Task.objects.get(id=f.task_id)
    assert task.title.startswith("Follow up with") and task.due == timezone.localtime(f.due_at).date()
    assert task.source["kind"] == "mail_followup" and task.source["followup"] == f.pk
    # Someone replies: the nudge closes and its task is completed.
    from mail.testing.corpus import simple

    raw = simple(500, "Alice Example <alice@friends.test>", "Re: Trip planning", "Sounds good!",
                 extra=[("In-Reply-To", "<trip2@friends.test>"), ("References", "<trip0@manifest.test> <trip2@friends.test>")],
                 date=timezone.now())
    server.deliver("INBOX", raw, [], timezone.now())
    engine.sync_all()
    f.refresh_from_db()
    task.refresh_from_db()
    assert f.status == "done" and task.done


def test_completing_or_deleting_the_task_closes_the_nudge(loaded, api):
    t = _thread()
    f = _followup(api, t)
    r = api.patch(f"/api/tasks/{f.task_id}", {"done": True})
    assert r.status_code == 200
    f.refresh_from_db()
    assert f.status == "done"
    f2 = _followup(api, t)
    assert api.delete(f"/api/tasks/{f2.task_id}").status_code == 204
    f2.refresh_from_db()
    assert f2.status == "cancelled"


def test_moving_the_task_moves_the_nudge_and_back(loaded, api):
    t = _thread()
    f = _followup(api, t)
    new_day = (timezone.localdate() + dt.timedelta(days=10)).isoformat()
    api.patch(f"/api/tasks/{f.task_id}", {"due": new_day})
    f.refresh_from_db()
    assert timezone.localtime(f.due_at).date().isoformat() == new_day
    later = (timezone.now() + dt.timedelta(days=20)).isoformat()
    api.post(f"/api/followups/{f.id}", {"action": "later", "until": later})
    assert Task.objects.get(id=f.task_id).due == (timezone.localtime(timezone.now() + dt.timedelta(days=20))).date()


def test_cancel_in_mail_removes_task_done_completes_it(loaded, api):
    t = _thread()
    f = _followup(api, t)
    api.post(f"/api/followups/{f.id}", {"action": "cancel"})
    assert not Task.objects.filter(id=f.task_id).exists()
    f2 = _followup(api, t)
    api.post(f"/api/followups/{f2.id}", {"action": "done"})
    assert Task.objects.get(id=f2.task_id).done


def test_nudge_from_composer_makes_task(loaded, api, settings):
    from mail.imap.fake import FakeSender
    from mail.outbox import Executor

    settings.MAIL = {"SEND_UNDO_SECONDS": 0}
    m = Message.objects.get(message_id="trip2@friends.test")
    d = api.post("/api/drafts", {"mode": "reply", "inReplyTo": m.pk, "to": [{"addr": "alice@friends.test", "name": "Alice"}],
                                 "subject": "Re: Trip planning", "bodyHtml": "<p>?</p>",
                                 "followupAt": (timezone.now() + dt.timedelta(days=2)).isoformat()}).json()
    api.post(f"/api/drafts/{d['id']}/send")
    Executor(loaded, FakeSender()).run_pending()
    f = FollowUp.objects.get(message_key=Draft.objects.get(pk=d["id"]).message_id)
    assert Task.objects.get(id=f.task_id).title == "Follow up with Alice: Re: Trip planning"


def test_today_summary(loaded, api):
    r = api.get("/api/today").json()
    assert r["connected"] and r["unread"] > 0 and r["latest"]
    assert all("high" != Message.objects.filter(thread_id=x["threadId"]).first().risk_level for x in r["latest"])
