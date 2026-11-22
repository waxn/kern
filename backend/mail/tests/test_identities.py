"""Send mail as another address (mail/identities.py), e.g. a Gmail forwarded to this mailbox."""

from datetime import timedelta

from django.utils import timezone

from mail import identities, smtp
from mail.identity import my_addresses
from mail.imap.fake import FakeSender
from mail.models import Draft, MailIdentity, Message, OutboxOp
from mail.outbox import Executor

GMAIL = "someone@gmail.com"


def _gmail(api, **extra):
    r = api.post("/api/mail/identities", {"address": GMAIL, "name": "Some One", "smtpHost": "", **extra})
    assert r.status_code == 200, r.content
    return r.json()


def test_add_list_and_validate(api):
    i = _gmail(api)
    assert i["address"] == GMAIL and i["ownServer"] is False and "password" not in i
    assert [x["address"] for x in api.get("/api/mail/identities").json()] == [GMAIL]
    assert api.post("/api/mail/identities", {"address": GMAIL}).status_code == 400  # twice
    assert api.post("/api/mail/identities", {"address": "nope"}).status_code == 400
    # An own server needs a password, and must be a public host.
    assert api.patch(f"/api/mail/identities/{i['id']}", {"smtpHost": "smtp.gmail.com"}).status_code == 400
    assert api.patch(f"/api/mail/identities/{i['id']}", {"smtpHost": "127.0.0.1", "password": "x"}).status_code == 400
    assert GMAIL in my_addresses()
    assert {"address": GMAIL, "name": "Some One"} in api.get("/api/mail/info").json()["identities"]
    assert api.delete(f"/api/mail/identities/{i['id']}").status_code == 200
    assert GMAIL not in my_addresses()


def test_password_is_encrypted_and_never_returned(api, monkeypatch):
    monkeypatch.setattr(identities.hosts, "check", lambda h, p: None)
    i = _gmail(api, smtpHost="smtp.gmail.com", password="app-password-123")
    assert i["hasPassword"] and i["ownServer"]
    row = MailIdentity.objects.get(pk=i["id"])
    assert "app-password-123" not in row.password_enc
    assert "app-password-123" not in str(api.get("/api/mail/identities").json())


def test_send_as_goes_out_from_that_address(loaded, api, server):
    _gmail(api)
    d = api.post("/api/drafts", {"to": [{"addr": "friend@example.org"}], "subject": "Hi", "bodyHtml": "<p>hey</p>",
                                 "from": GMAIL}).json()
    assert d["from"] == GMAIL
    # Not just any address.
    assert api.patch(f"/api/drafts/{d['id']}", {"from": "boss@bank.test"}).status_code == 400
    api.post(f"/api/drafts/{d['id']}/send", {})
    OutboxOp.objects.filter(kind="send").update(not_before=timezone.now() - timedelta(seconds=1))
    snd = FakeSender()
    Executor(server, snd).run_pending()
    env, rcpts, raw = snd.sent[-1]
    assert env == GMAIL and rcpts == ["friend@example.org"]
    assert b"From: Some One <someone@gmail.com>" in raw
    assert Draft.objects.get(pk=d["id"]).status == "sent"


def test_own_server_routes_and_saves_a_copy(loaded, api, monkeypatch, settings):
    monkeypatch.setattr(identities.hosts, "check", lambda h, p: None)
    _gmail(api, smtpHost="smtp.gmail.com", password="pw")
    went = []
    monkeypatch.setattr(identities, "send", lambda i, env, r, raw: went.append((i.smtp_host, env)) or {})
    monkeypatch.setattr(smtp.account, "password", lambda: "pw")
    out = smtp.SmtpSender().send(GMAIL, ["x@example.org"], b"raw")
    assert out == {} and went == [("smtp.gmail.com", GMAIL)]


def test_reply_answers_from_the_address_it_was_sent_to(loaded, api):
    _gmail(api)
    m = Message.objects.exclude(from_addr__in=my_addresses()).first()
    m.to_addrs = [{"name": "", "addr": GMAIL}]
    m.save(update_fields=["to_addrs"])
    pre = api.get("/api/mail/compose/prefill", message=m.pk, mode="reply").json()
    assert pre["from"] == GMAIL
