import pytest

from mail import private_ai
from mail.models import Folder, FolderRole, Message
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def inbox():
    return Folder.objects.get(role=FolderRole.INBOX)


def mail(n, sender="promo@stranger.test", subject="You won a prize"):
    return corpus.msg([("From", f"Promo <{sender}>"), ("To", corpus.ME), ("Subject", subject),
                       ("Message-ID", f"<pa{n}@stranger.test>"), ("Date", "Mon, 16 Nov 2026 10:00:00 +0000")], "Claim now")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def off(*a, **k):
        raise private_ai.PrivateAIError("off")

    monkeypatch.setattr(private_ai, "_request", off)


@pytest.fixture
def on(api):
    r = api.post("/api/private-ai", {"baseUrl": "http://192.168.1.20:1234/v1/", "model": "qwen"})
    assert r.status_code == 200
    private_ai._state.clear()


def test_verdict_parsing():
    assert private_ai.verdict("junk") == "junk"
    assert private_ai.verdict("<think>maybe inbox?</think>\nJunk.") == "junk"
    assert private_ai.verdict("Inbox") == "inbox"
    assert private_ai.verdict("<think>still thinking about junk") is None
    assert private_ai.verdict("no idea") is None


def test_settings_roundtrip_hides_key_and_allows_http(api):
    r = api.post("/api/private-ai", {"baseUrl": "http://pc.lan:1234/v1/", "key": "sk-secret", "timeout": 5})
    d = r.json()
    assert d["baseUrl"] == "http://pc.lan:1234/v1" and d["hasKey"] and d["timeout"] == 10
    assert "sk-secret" not in r.content.decode()
    assert d["online"] is False  # nothing listens there; no error, just offline
    assert api.post("/api/private-ai", {"baseUrl": "ftp://x"}).status_code == 400


def test_junk_verdict_moves_new_mail(loaded, on, engine, server, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "junk")
    server.deliver("INBOX", mail(1))
    engine.sync_folder(inbox())
    assert Message.objects.get(message_id="pa1@stranger.test").folder.role == FolderRole.JUNK


def test_inbox_verdict_and_offline_leave_mail_alone(loaded, on, engine, server, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "inbox")
    server.deliver("INBOX", mail(2))

    def down(*a, **k):
        raise private_ai.PrivateAIError("off")

    engine.sync_folder(inbox())
    monkeypatch.setattr(private_ai, "complete", down)
    server.deliver("INBOX", mail(3))
    server.deliver("INBOX", mail(4))
    engine.sync_folder(inbox())
    for n in (2, 3, 4):
        assert Message.objects.get(message_id=f"pa{n}@stranger.test").folder.role == FolderRole.INBOX


def test_people_you_wrote_to_are_never_judged(loaded, on, engine, server, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "junk")
    server.deliver("INBOX", mail(5, sender="alice@friends.test", subject="hi"))
    engine.sync_folder(inbox())
    assert Message.objects.get(message_id="pa5@stranger.test").folder.role == FolderRole.INBOX


def test_sorting_off_does_nothing(loaded, api, on, engine, server, monkeypatch):
    api.post("/api/private-ai", {"sortMail": False})
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "junk")
    server.deliver("INBOX", mail(6))
    engine.sync_folder(inbox())
    assert Message.objects.get(message_id="pa6@stranger.test").folder.role == FolderRole.INBOX
