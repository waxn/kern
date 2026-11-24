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


def test_address_without_path_gets_v1(api):
    d = api.post("/api/private-ai", {"baseUrl": "http://192.168.0.113:1234"}).json()
    assert d["baseUrl"] == "http://192.168.0.113:1234/v1"
    d = api.post("/api/private-ai", {"baseUrl": "http://host:11434/v1/"}).json()
    assert d["baseUrl"] == "http://host:11434/v1"


def test_reason_is_kept_and_shown(loaded, on, engine, server, api, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "<think>hm</think>VERDICT: junk\nREASON: Unsolicited prize offer from an unknown sender.")
    server.deliver("INBOX", mail(7))
    engine.sync_folder(inbox())
    m = Message.objects.get(message_id="pa7@stranger.test")
    assert m.folder.role == FolderRole.JUNK and m.risk_score == Message.objects.get(pk=m.pk).risk_score
    body = api.get(f"/api/threads/{m.thread_id}").json()
    msg = next(x for x in body["messages"] if x["id"] == m.pk)
    assert msg["privateSort"] == {"verdict": "junk", "reason": "Unsolicited prize offer from an unknown sender."}
    assert all(f["rule"] != "private-sort" for f in msg["risk"]["findings"])


def test_reason_parsing():
    assert private_ai.verdict("VERDICT: inbox\nREASON: Looks like junk but it is a receipt.") == "inbox"
    assert private_ai.reason("VERDICT: inbox\nREASON: A receipt.") == "A receipt."


def test_unreadable_answer_is_explained(loaded, on, engine, server, api, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "<think>let me think about this")
    server.deliver("INBOX", mail(8))
    engine.sync_folder(inbox())
    m = Message.objects.get(message_id="pa8@stranger.test")
    assert m.folder.role == FolderRole.INBOX
    assert private_ai.note_for(m)["verdict"] == "unclear"


def test_token_limit_and_guidance_are_settings(api):
    d = api.post("/api/private-ai", {"baseUrl": "http://pc:1234", "maxTokens": 20000, "guidance": "Shops are junk."}).json()
    assert d["maxTokens"] == 20000 and d["guidance"] == "Shops are junk."
    assert api.get("/api/private-ai").json()["maxTokens"] == 20000


def test_load_images_preference(loaded, api):
    assert api.patch("/api/preferences", {"load_images": True}).json()["load_images"] is True


def test_activity_log_records_each_decision(loaded, on, engine, server, api, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "VERDICT: junk\nREASON: An ad.")
    server.deliver("INBOX", mail(9))
    engine.sync_folder(inbox())
    act = api.get("/api/private-ai").json()["activity"]
    assert act[0]["event"] == "junk" and act[0]["reason"] == "An ad." and act[0]["from"] == "promo@stranger.test"


def test_offline_is_logged_then_backed_off(loaded, on, engine, server, api):
    server.deliver("INBOX", mail(10))
    server.deliver("INBOX", mail(11))
    engine.sync_folder(inbox())
    events = [a["event"] for a in api.get("/api/private-ai").json()["activity"]]
    assert events[:2] == ["skipped", "offline"]


def test_test_button(api, on, monkeypatch):
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: "VERDICT: junk\nREASON: Sells pens.")
    d = api.post("/api/private-ai/test").json()
    assert d["ok"] and d["verdict"] == "junk" and d["entry"]["test"] is True


LIVE = __import__("os").environ.get("KERN_LIVE_PRIVATE_AI", "")


@pytest.mark.skipif(not LIVE, reason="set KERN_LIVE_PRIVATE_AI=http://host:1234/v1 to test a real model")
def test_live_model_sorts_an_ad_into_junk(loaded, api, engine, server, monkeypatch):
    monkeypatch.undo()  # talk to the real endpoint
    api.post("/api/private-ai", {"baseUrl": LIVE, "model": __import__("os").environ.get("KERN_LIVE_MODEL", "")})
    private_ai._state.clear()
    server.deliver("INBOX", corpus.msg([("From", "Pentel <news@pentel.example>"), ("To", corpus.ME),
                                        ("Subject", "New EnerGel colors! 20% off this week"),
                                        ("Message-ID", "<live1@pentel.example>"), ("Date", "Mon, 16 Nov 2026 10:00:00 +0000")],
                                       "Discover our new pastel collection. Shop now and save 20% with code PASTEL20. Unsubscribe"))
    engine.sync_folder(inbox())
    m = Message.objects.get(message_id="live1@pentel.example")
    print(api.get("/api/private-ai").json()["activity"][0])
    assert m.folder.role == FolderRole.JUNK
    body = api.get(f"/api/threads/{m.thread_id}").json()
    assert next(x for x in body["messages"] if x["id"] == m.pk)["privateSort"]["verdict"] == "junk"


def test_feedback_becomes_a_rule_the_model_reads(loaded, on, engine, server, api, monkeypatch):
    seen = []
    monkeypatch.setattr(private_ai, "complete", lambda s, p, **k: seen.append(s) or "VERDICT: inbox\nREASON: A job alert.")
    server.deliver("INBOX", mail(9, sender="jobs@linkedin.test", subject="New jobs for you"))
    engine.sync_folder(inbox())
    m = Message.objects.get(message_id="pa9@stranger.test")
    r = api.post(f"/api/messages/{m.pk}/private-feedback", {"text": "I don't use LinkedIn, so their normal emails can go to junk."})
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert "jobs@linkedin.test" in rule and "the Inbox" in rule and "don't use LinkedIn" in rule
    assert rule in api.get("/api/private-ai").json()["guidance"]
    assert api.post(f"/api/messages/{m.pk}/private-feedback", {"text": "  "}).status_code == 400

    server.deliver("INBOX", mail(10, sender="jobs@linkedin.test", subject="More jobs"))
    engine.sync_folder(inbox())
    assert "don't use LinkedIn" in seen[-1]
