"""Kern integration: two-factor sign-in, the mail guard, account settings,
live changes, the per-user supervisor and backups."""
import json
import sqlite3
import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts import site, totp
from accounts.models import TOTPDevice
from kern import secretbox
from mail import account, hosts, lifecycle
from mail.models import ChangeEvent, MailAccount, Message, Snooze

from .conftest import PASSWORD, ApiClient, current_code


def _login(username="me", password=PASSWORD, code=None):
    c = ApiClient(Client())
    body = {"username": username, "password": password}
    if code is not None:
        body["code"] = code
    return c, c.post("/api/auth/login", body)


# --- two-factor sign-in --------------------------------------------------------

def test_login_asks_for_code_then_accepts_it(user):
    c, r = _login()
    assert r.status_code == 401 and r.json()["needs_code"] is True
    assert c.get("/api/site").json()["user"] is None  # not signed in yet
    c, r = _login(code="000000")
    assert r.status_code == 401 and r.json()["needs_code"]
    c, r = _login(code=current_code(user._totp_secret))
    assert r.status_code == 200 and r.json()["user"]["two_factor"] is True
    # The same code can't be used twice (replay).
    c2, r2 = _login(code=current_code(user._totp_secret))
    assert r2.status_code == 401


def test_recovery_code_signs_in_once(user):
    codes = totp.new_recovery_codes(user)
    c, r = _login(code=codes[0])
    assert r.status_code == 200
    c, r = _login(code=codes[0])
    assert r.status_code == 401


def test_wrong_codes_are_throttled(user):
    for _ in range(8):
        _login(code="123456")
    c, r = _login(code=current_code(user._totp_secret))
    assert r.status_code == 429


def test_setup_confirm_disable_flow(db):
    site.mark_setup_complete()
    u = get_user_model().objects.create_user("bob", password=PASSWORD)
    c, r = _login("bob")
    assert r.status_code == 200 and r.json()["user"]["two_factor"] is False
    other, _ = _login("bob")  # another browser, signed in with the password only
    assert c.post("/api/auth/2fa/setup", {"password": "wrong"}).status_code == 403
    s = c.post("/api/auth/2fa/setup", {"password": PASSWORD}).json()
    assert s["uri"].startswith("otpauth://totp/") and "<svg" in s["qr_svg"]
    assert not totp.enabled(u)
    assert c.post("/api/auth/2fa/confirm", {"code": "000000"}).status_code == 400
    r = c.post("/api/auth/2fa/confirm", {"code": current_code(s["secret"])}).json()
    assert r["enabled"] and len(r["recovery_codes"]) == 10 and r["signed_out"] == 1
    assert other.get("/api/site").json()["user"] is None  # the other session was signed out
    st = c.get("/api/auth/2fa").json()
    assert st["enabled"] and st["session_verified"] and st["recovery_left"] == 10
    # The seed is encrypted at rest.
    d = TOTPDevice.objects.get(user=u)
    assert s["secret"] not in d.secret_enc
    # Can't turn it off while mail is connected.
    assert c.post("/api/auth/2fa/disable", {"password": PASSWORD, "code": current_code(s["secret"], 1)}).status_code == 409
    MailAccount.objects.filter(pk=1).update(enabled=False)
    r = c.post("/api/auth/2fa/disable", {"password": PASSWORD, "code": current_code(s["secret"], 1)})
    assert r.status_code == 200 and not totp.enabled(u)


def test_git_needs_git_password_when_2fa_on(user):
    import base64

    from notes.views_git import _basic_user

    class R:
        META = {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"me:{PASSWORD}".encode()).decode(),
                "REMOTE_ADDR": "1.2.3.4"}

    assert _basic_user(R()) is None  # account password refused with 2FA on


# --- the mail guard -------------------------------------------------------------

def test_mail_needs_2fa_session(user):
    # Signed in with password only (2FA turned on afterwards in another session):
    TOTPDevice.objects.filter(user=user).delete()
    c, r = _login()
    assert r.status_code == 200
    r = c.get("/api/mail/threads")
    assert r.status_code == 403 and r.json()["code"] == "needs_2fa"
    totp.start_setup(user)
    TOTPDevice.objects.filter(user=user).update(confirmed=True)
    r = c.get("/api/mail/threads")
    assert r.status_code == 403 and r.json()["code"] == "needs_2fa_session"
    st = c.get("/api/mail/account/status").json()  # open, but says what's missing
    assert st["two_factor"] == {"enabled": True, "session_verified": False}
    assert st["account"] == {"address": "me@manifest.test"}


def test_mail_api_needs_sign_in(anon):
    assert anon.get("/api/mail/threads").status_code == 401
    assert anon.get("/api/mail/account/status").status_code == 401


# --- account settings ------------------------------------------------------------

def test_account_password_is_write_only(api, monkeypatch):
    monkeypatch.setattr(hosts, "check", lambda h, p: None)
    r = api.put("/api/mail/account", {"address": "Me@Example.com", "imap_host": "imap.example.com",
                                      "smtp_host": "smtp.example.com", "password": "hunter2-mail"})
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["account"]["address"] == "me@example.com" and body["account"]["has_password"]
    assert "hunter2" not in json.dumps(body) and "password_enc" not in json.dumps(body)
    a = MailAccount.objects.get(pk=1)
    assert "hunter2" not in a.password_enc and secretbox.decrypt(a.password_enc) == "hunter2-mail"
    v = a.version
    # Saving without a password keeps the stored one; the version bumps (worker restarts).
    r = api.put("/api/mail/account", {"from_name": "Me"}).json()
    assert MailAccount.objects.get(pk=1).version == v + 1
    assert secretbox.decrypt(MailAccount.objects.get(pk=1).password_enc) == "hunter2-mail"
    assert api.put("/api/mail/account", {"imap_host": "imap.example.com\r\nX"}).status_code == 400
    assert api.put("/api/mail/account", {"smtp_security": "none"}).status_code == 400


def test_private_mail_hosts_refused(api):
    r = api.put("/api/mail/account", {"address": "me@example.com", "imap_host": "127.0.0.1",
                                      "smtp_host": "127.0.0.1", "password": "x"})
    assert r.status_code == 400 and "private network" in r.json()["detail"]
    with pytest.raises(hosts.HostNotAllowed):
        hosts.check("10.0.0.5", 993)
    site.update({"allow_local_mail": True})
    hosts.check("10.0.0.5", 993)  # an admin allowed local mail servers


def test_admin_can_turn_mail_off(api, monkeypatch):
    monkeypatch.setattr(hosts, "check", lambda h, p: None)
    site.update({"allow_mail": False})
    r = api.put("/api/mail/account", {"address": "me@example.com", "imap_host": "i.example.com",
                                      "smtp_host": "s.example.com", "password": "x"})
    assert r.status_code == 403


def test_disconnect_forgets_password_and_optionally_mail(loaded, api):
    assert Message.objects.exists()
    r = api.delete("/api/mail/account").json()
    assert r["connected"] is False
    a = MailAccount.objects.get(pk=1)
    assert a.password_enc == "" and not a.enabled
    assert Message.objects.exists()  # kept unless asked
    api.c.delete("/api/mail/account?forget=1", HTTP_X_KERN="1", HTTP_SEC_FETCH_SITE="same-origin")
    assert not Message.objects.exists()


# --- live changes -----------------------------------------------------------------

def test_changes_poll(api):
    from mail import events

    first = api.get("/api/mail/changes").json()
    assert first["events"] == []
    events.emit("message", thread=1, new=True)
    events.emit("update", threads=[1, 2])
    r = api.get("/api/mail/changes", since=first["last"]).json()
    assert [e["kind"] for e in r["events"]] == ["message", "update"] and r["events"][0]["new"] is True
    assert api.get("/api/mail/changes", since=r["last"]).json()["events"] == []
    assert api.get("/api/mail/changes", since=r["last"] + 1000).json()["reset"] is True


# --- supervisor -------------------------------------------------------------------

class _FakeWorker:
    def __init__(self):
        self.stop = threading.Event()
        self.started = threading.Event()

    def run_forever(self):
        self.started.set()
        self.stop.wait(10)

    def shutdown(self):
        self.stop.set()


def test_supervisor_follows_account_changes(user):
    from mail.supervisor import Supervisor

    made = []

    def factory(uid):
        w = _FakeWorker()
        made.append(w)
        return w

    def wait_for(n):
        for _ in range(200):
            if len(made) >= n and made[n - 1].started.is_set():
                return True
            time.sleep(0.01)
        return False

    sup = Supervisor(factory=factory)
    sup.scan()
    assert wait_for(1)
    sup.scan()
    assert len(made) == 1  # unchanged: same worker
    MailAccount.objects.filter(pk=1).update(version=5)
    sup.scan()
    assert wait_for(2) and made[0].stop.is_set()  # restarted with new settings
    MailAccount.objects.filter(pk=1).update(enabled=False)
    sup.scan()
    assert made[1].stop.is_set() and not sup.threads
    MailAccount.objects.filter(pk=1).update(enabled=True)
    TOTPDevice.objects.filter(user=user).delete()  # no 2FA, no mail
    sup.scan()
    assert not sup.threads
    sup.stop_all()


# --- backups ----------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_backup_copy_leaves_messages_out(loaded, tmp_path):
    from django.db import connection

    snap = tmp_path / "snap.sqlite3"
    dst = sqlite3.connect(snap)
    connection.ensure_connection()
    with dst:
        connection.connection.backup(dst)
    assert dst.execute("SELECT count(*) FROM mail_message").fetchone()[0] > 0
    lifecycle.scrub_backup(dst)
    assert dst.execute("SELECT count(*) FROM mail_message").fetchone()[0] == 0
    assert dst.execute("SELECT count(*) FROM mail_mailaccount").fetchone()[0] == 1
    hits = dst.execute("SELECT count(*) FROM mail_message_fts WHERE mail_message_fts MATCH 'lisbon'").fetchone()[0]
    assert hits == 0
    dst.close()


def test_after_restore_resyncs_and_drops_foreign_password(loaded, engine, server):
    a = MailAccount.objects.get(pk=1)
    a.password_enc = "gAAAAA-not-from-this-key"
    a.save()
    Snooze.objects.create(wake_at="2030-01-01T00:00:00Z", message_keys=["trip2@friends.test"])
    lifecycle.after_restore()
    assert not Message.objects.exists()
    a.refresh_from_db()
    assert a.password_enc == "" and not a.enabled
    assert Snooze.objects.count() == 1  # user data kept
    engine.sync_all()
    assert Message.objects.exists()  # downloaded again
