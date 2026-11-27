from mail import account
import email

import pytest

from mail import preferences, sending
from mail.models import Draft

pytestmark = pytest.mark.django_db


def test_defaults_and_validation(api):
    p = api.get("/api/preferences").json()
    assert p["after_action"] == "next" and p["undo_seconds"] is None
    assert api.patch("/api/preferences", {"after_action": "sideways"}).status_code == 400
    assert api.patch("/api/preferences", {"nope": 1}).status_code == 400
    r = api.patch("/api/preferences", {"undo_seconds": 999, "from_name": "  Linus   T  ", "signature": "x" * 9000})
    assert r.status_code == 200
    p = r.json()
    assert p["undo_seconds"] == 60 and p["from_name"] == "Linus T" and len(p["signature"]) == 4000


def test_from_name_and_undo_used_when_sending(db, settings):
    preferences.update({"from_name": "Someone Else", "undo_seconds": 3})
    d = Draft.objects.create(message_id="x@manifest.test", to_addrs=[{"name": "", "addr": "a@b.test"}], subject="Hi",
                             body_html="<p>Hello</p>")
    raw = sending.build_mime(d)
    assert email.message_from_bytes(raw)["From"].startswith("Someone Else")
    sending.queue_send(d)
    d.refresh_from_db()
    assert (d.send_at - d.updated).total_seconds() == pytest.approx(3, abs=1)
    assert preferences.undo_seconds() == 3
    preferences.update({"undo_seconds": None})
    assert preferences.undo_seconds() == account.cfg()["SEND_UNDO_SECONDS"]


def test_saving_a_preference_keeps_other_settings_in_the_row(api, monkeypatch):
    """Preferences.data also holds the private model, tracking and geo settings."""
    from mail import private_ai

    monkeypatch.setattr(private_ai, "_request", lambda *a, **k: (_ for _ in ()).throw(private_ai.PrivateAIError("off")))
    assert api.post("/api/private-ai", {"baseUrl": "http://pc.lan:1234/v1", "model": "qwen", "guidance": "no ads"}).status_code == 200
    assert api.patch("/api/preferences", {"load_images": True}).status_code == 200
    c = private_ai._cfg()
    assert c["base_url"] == "http://pc.lan:1234/v1" and c["model"] == "qwen" and c["guidance"] == "no ads"
    assert private_ai.configured()
