"""Malformed requests get a 400 or 404 with words a person can read, never a 500."""
import email

import pytest

from mail.models import Draft, Message
from mail.outbox import Executor
from mail.sending import build_for_send, validate_recipients

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("ids", [[None], 5, "12", [True], ["x"], [{"id": 1}]])
def test_thread_actions_want_a_list_of_ids(loaded, api, ids):
    r = api.post("/api/threads/actions", {"ids": ids, "action": "archive"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Expected a list of ids."


def test_message_actions_want_a_list_of_ids(loaded, api):
    r = api.post("/api/messages/actions", {"ids": [None], "action": "read"})
    assert r.status_code == 400 and r.json()["detail"] == "Expected a list of ids."


def test_ids_as_strings_of_digits_still_work(loaded, api):
    t = Message.objects.get(subject="Lunch on Friday?").thread
    assert api.post("/api/threads/actions", {"ids": [str(t.pk)], "action": "star"}).status_code == 200


def test_prefill_for_a_message_that_is_not_a_number(loaded, api):
    assert api.get("/api/compose/prefill", message="abc", mode="reply").status_code == 404


def test_label_without_a_name(loaded, api):
    r = api.post("/api/labels", {"name": None})
    assert r.status_code == 400
    assert not api.get("/api/labels").json()


def test_undo_seconds_not_a_number(loaded, api):
    r = api.patch("/api/preferences", {"undo_seconds": "soon"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Undo time is a number of seconds, 0 to 60."


def test_recipients_as_one_string():
    out = validate_recipients('"Doe, Jane" <jane@x.test>, bob@y.test')
    assert out == [{"name": "Doe, Jane", "addr": "jane@x.test"}, {"name": "", "addr": "bob@y.test"}]
    assert validate_recipients(None) == []


def test_draft_with_recipients_as_a_string(loaded, api):
    d = api.post("/api/drafts", {"mode": "new", "to": "bob@y.test, Ann <ann@z.test>"})
    assert d.status_code == 200
    assert [a["addr"] for a in d.json()["to"]] == ["bob@y.test", "ann@z.test"]


def test_someone_in_to_and_cc_gets_one_copy(loaded, api, server, settings):
    settings.MAIL = {**settings.MAIL, "SEND_UNDO_SECONDS": 0}
    d = api.post("/api/drafts", {"to": ["bob@y.test"], "cc": ["Bob@Y.test", "ann@z.test"],
                                 "bcc": ["ann@z.test"], "subject": "Plan", "bodyHtml": "<p>Hi</p>"}).json()
    assert build_for_send(Draft.objects.get(pk=d["id"]))[2] == ["bob@y.test", "ann@z.test"]
    api.post(f"/api/drafts/{d['id']}/send")
    from mail.imap.fake import FakeSender

    snd = FakeSender()
    Executor(server, snd).run_pending()
    assert len(snd.sent) == 1
    _, rcpts, raw = snd.sent[0]
    assert sorted(r.lower() for r in rcpts) == ["ann@z.test", "bob@y.test"]
    # The headers still show who was asked to read it, as written.
    assert email.message_from_bytes(raw)["Cc"] == "Bob@Y.test, ann@z.test"
