"""ThreadFolder (the per-folder conversation index) must always agree with the
messages, whatever changes them: sync, local actions, flag changes from other
clients, expunges. The fast folder listing reads only this index."""

import time

import pytest
from django.db.models import Exists, OuterRef

from mail import events
from mail.models import ChangeEvent, Folder, FolderRole, Message, Thread, ThreadFolder
from mail.threads import rebuild_thread_index

pytestmark = pytest.mark.django_db


def expected_index() -> dict[tuple[int, int], bool]:
    rows: dict[tuple[int, int], bool] = {}
    for tid, fid, seen in Message.objects.filter(thread__isnull=False).values_list("thread_id", "folder_id", "seen"):
        rows[(fid, tid)] = rows.get((fid, tid), False) or not seen
    return rows


def actual_index() -> dict[tuple[int, int], bool]:
    return {(fid, tid): u for fid, tid, u in ThreadFolder.objects.values_list("folder_id", "thread_id", "unread")}


def assert_index_matches():
    assert actual_index() == expected_index()
    dates = dict(Thread.objects.values_list("id", "last_date"))
    for tid, d in ThreadFolder.objects.values_list("thread_id", "last_date"):
        assert d == dates[tid]


def inbox() -> Folder:
    return Folder.objects.get(role=FolderRole.INBOX)


def slow_inbox_ids(unread=False) -> list[int]:
    """The old query (Exists over messages): what the index must reproduce."""
    q = Message.objects.filter(thread=OuterRef("pk"), folder=inbox())
    if unread:
        q = q.filter(seen=False)
    return list(Thread.objects.filter(Exists(q)).order_by("-last_date", "-id").values_list("id", flat=True))


def test_index_after_initial_sync(loaded):
    assert ThreadFolder.objects.exists()
    assert_index_matches()


def test_rebuild_is_idempotent(loaded):
    before = actual_index()
    rebuild_thread_index()
    assert actual_index() == before


def test_listing_matches_the_old_query(loaded, api, monkeypatch):
    from mail.api import views

    monkeypatch.setattr(views, "PAGE", 7)
    for unread in (False, True):
        got, cursor = [], None
        while True:
            params = {"view": "inbox"}
            if unread:
                params["unread"] = "1"
            if cursor:
                params["cursor"] = cursor
            r = api.get("/api/threads", **params).json()
            got += [t["id"] for t in r["threads"]]
            cursor = r["next"]
            if not cursor:
                break
        assert got == slow_inbox_ids(unread)


def test_role_name_views(loaded, api):
    by_role = api.get("/api/threads", view="inbox").json()
    by_id = api.get("/api/threads", view=f"folder:{inbox().pk}").json()
    assert by_role == by_id
    assert api.get("/api/threads", view="snoozed").status_code in (200, 404)


def test_index_follows_actions(loaded, api):
    t = Message.objects.filter(folder=inbox()).first().thread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "read"})
    assert_index_matches()
    assert not ThreadFolder.objects.get(thread=t, folder=inbox()).unread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "unread"})
    assert ThreadFolder.objects.get(thread=t, folder=inbox()).unread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "archive", "context": inbox().pk})
    assert_index_matches()
    assert not ThreadFolder.objects.filter(thread=t, folder=inbox()).exists()
    assert t.pk not in [x["id"] for x in api.get("/api/threads", view="inbox").json()["threads"]]
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "inbox"})
    assert_index_matches()


def test_index_follows_server_changes(loaded, server, engine):
    m = Message.objects.filter(folder=inbox(), seen=False).first()
    server.select("INBOX", readonly=False)
    server.store_flags([m.uid], ["\\Seen"], [])
    engine.sync_folder(inbox())
    assert_index_matches()
    server.select("INBOX", readonly=False)
    server.store_flags([m.uid], ["\\Deleted"], [])
    server.expunge_uids([m.uid])
    engine.sync_folder(inbox())
    assert_index_matches()


def test_folder_counts_use_the_index(loaded, api):
    data = api.get("/api/folders").json()
    f = next(x for x in data["folders"] if x["role"] == "inbox")
    assert f["total"] == len(slow_inbox_ids())
    assert f["unread"] == len(slow_inbox_ids(unread=True))


def test_mark_everything_in_view_read(loaded, api):
    assert ThreadFolder.objects.filter(folder=inbox(), unread=True).exists()
    r = api.post("/api/threads/actions", {"all": {"view": "inbox"}, "action": "read"}).json()
    assert r["count"] == len(slow_inbox_ids())
    assert not ThreadFolder.objects.filter(folder=inbox(), unread=True).exists()
    assert not Message.objects.filter(thread_id__in=slow_inbox_ids(), seen=False).exists()
    api.post("/api/threads/actions", {"all": {"view": "inbox"}, "action": "unread"})
    assert ThreadFolder.objects.filter(folder=inbox(), unread=False).count() == 0
    assert_index_matches()


def test_select_all_refuses_risky_actions(loaded, api):
    r = api.post("/api/threads/actions", {"all": {"view": "inbox"}, "action": "delete_forever"})
    assert r.status_code == 400


def test_changes_long_poll_returns_on_news(loaded, api, monkeypatch):
    from mail.api import views

    monkeypatch.setattr(views, "LONG_POLL_TICK", 0.02)
    last = api.get("/api/changes").json()["last"]
    t0 = time.monotonic()
    r = api.get("/api/changes", since=last, wait=1).json()
    assert r["events"] == [] and time.monotonic() - t0 >= 0.9

    # Something happens while the request waits (the worker emits an event).
    real_sleep = time.sleep
    calls = []

    def sleep(sec):
        calls.append(sec)
        if len(calls) == 3:
            events.emit("message", folder=inbox().pk, thread=1, new=True)
        real_sleep(sec)

    monkeypatch.setattr(time, "sleep", sleep)
    t0 = time.monotonic()
    r = api.get("/api/changes", since=last, wait=5).json()
    assert time.monotonic() - t0 < 2 and len(calls) == 3
    assert [e["kind"] for e in r["events"]] == ["message"]
    assert ChangeEvent.objects.count() >= 1


def test_check_now_syncs_and_reports(loaded, api, server, executor):
    from mail.models import OpStatus, OutboxOp

    assert api.post("/api/check").json()["queued"]
    api.post("/api/check")  # a second click doesn't queue another
    assert OutboxOp.objects.filter(kind="check", status=OpStatus.PENDING).count() == 1
    executor.run_pending()
    assert executor.checked and inbox().pk in executor.touched_folders


def test_empty_html_is_not_shown_as_a_page():
    from mail.api.views import _shows_anything

    assert not _shows_anything("<div><br></div><p>&nbsp;</p><style>p{color:red}</style><!-- x -->")
    assert not _shows_anything("<html><head><title>Hi</title></head><body> ​ </body></html>")
    assert _shows_anything("<p>Hello</p>")
    assert _shows_anything('<img src="/api/mail/messages/1/attachments/2">')
    assert _shows_anything('<td style="background-image: url(x)"></td>')
