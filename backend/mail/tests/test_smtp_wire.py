"""The real SMTP sender against a minimal wire-level SMTP server."""

import base64
import smtplib
import socketserver
import threading

import pytest

from mail.smtp import SmtpSender


class _SMTP(socketserver.StreamRequestHandler):
    def reply(self, line):
        self.wfile.write(line.encode() + b"\r\n")

    def handle(self):
        srv = self.server
        self.reply("220 test ESMTP")
        rcpts, sender = [], None
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode().strip()
            up = cmd.upper()
            if up.startswith(("EHLO", "HELO")):
                self.reply("250-test")
                self.reply("250 AUTH PLAIN LOGIN")
            elif up.startswith("AUTH PLAIN"):
                creds = base64.b64decode(cmd.split()[2]).split(b"\0")
                ok = creds[1:] == [srv.user.encode(), srv.password.encode()]
                self.reply("235 ok" if ok else "535 bad credentials")
            elif up.startswith("MAIL FROM:"):
                sender = cmd[10:].strip("<> ")
                self.reply("250 ok")
            elif up.startswith("RCPT TO:"):
                rcpt = cmd[8:].strip("<> ")
                if rcpt in srv.reject:
                    self.reply("550 no such user")
                else:
                    rcpts.append(rcpt)
                    self.reply("250 ok")
            elif up == "DATA":
                self.reply("354 go")
                data = b""
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    data += chunk[1:] if chunk.startswith(b"..") else chunk
                srv.delivered.append((sender, list(rcpts), data))
                self.reply("250 queued")
            elif up == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("250 ok")


class SMTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _SMTP)
        self.user, self.password = "me@manifest.test", "test-mail-password"
        self.reject = {"nobody@x.test"}
        self.delivered = []


@pytest.fixture
def smtpd(settings, monkeypatch):
    from kern import secretbox
    from mail import account
    from mail.models import MailAccount

    srv = SMTPServer()
    MailAccount.objects.filter(pk=1).update(password_enc=secretbox.encrypt(srv.password))
    account.invalidate()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    settings.MAIL = {**settings.MAIL, "SMTP_HOST": "127.0.0.1", "SMTP_PORT": srv.server_address[1],
                     "SMTP_SECURITY": "ssl", "USERNAME": "me@manifest.test"}
    # The test server is plain TCP; production code path is otherwise unchanged.
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda host, port, timeout=None, context=None: smtplib.SMTP(host, port, timeout=timeout))
    yield srv
    srv.shutdown()
    srv.server_close()


RAW = b"From: Me <me@manifest.test>\r\nTo: a@x.test\r\nSubject: hi\r\n\r\nHello\r\n.leading dot line\r\n"


def test_send_delivers_and_reports_partial_refusals(smtpd):
    refused = SmtpSender().send("me@manifest.test", ["a@x.test", "nobody@x.test"], RAW)
    assert list(refused) == ["nobody@x.test"] and refused["nobody@x.test"][0] == 550
    sender, rcpts, data = smtpd.delivered[0]
    assert sender == "me@manifest.test" and rcpts == ["a@x.test"]
    assert b"Subject: hi" in data and b".leading dot line" in data  # dot-stuffing round trip


def test_send_fails_when_everyone_is_refused(smtpd):
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        SmtpSender().send("me@manifest.test", ["nobody@x.test"], RAW)


def test_bad_password_raises(smtpd):
    smtpd.password = "something-else"
    with pytest.raises(smtplib.SMTPAuthenticationError):
        SmtpSender().send("me@manifest.test", ["a@x.test"], RAW)
