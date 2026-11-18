"""Runs one sync worker per user with a connected mailbox.

Kern is multi-user: ``manage.py mail_worker`` (its own container) starts this
supervisor, which every few seconds looks at each active user's mail account
and keeps exactly one ``Worker`` thread (mail/worker.py) per connected
account, each running as that user (kern/tenancy.py). A worker is restarted
when its account settings change (MailAccount.version) and stopped when the
account is switched off, removed, two-factor is turned off, or an
administrator turns mail off.

SECURITY: the IMAP/SMTP connection parameters and password are read once,
inside the user's own context, and captured in the connect function, so
threads the worker starts (IDLE) never need to look anything up and can't
mix users. Hosts are checked again at every connect (mail/hosts.py).
"""
from __future__ import annotations

import logging
import threading

from django.contrib.auth.models import User
from django.db import connections

from kern import tenancy

log = logging.getLogger("kern.mail.supervisor")
SCAN_SECONDS = 15


def wanted_version(user) -> int | None:
    """The account version to run for this user, or None when mail is off."""
    from accounts import site, totp

    from . import account

    if not site.get_all().get("allow_mail", True) or not totp.enabled(user):
        return None
    with tenancy.use(user.id):
        a = account.get()
        if not (a and a.enabled and a.address and a.password_enc and a.imap_host and a.smtp_host):
            return None
        return a.version


def make_connect():
    """Inside a user's context: a connect() bound to their current settings."""
    from . import account, hosts
    from .imap.client import ImapClient

    c = dict(account.cfg())
    pw = account.password()

    def connect():
        hosts.check(c["IMAP_HOST"], c["IMAP_PORT"])
        return ImapClient(c["IMAP_HOST"], c["IMAP_PORT"], c["LOGIN"], pw, verify_tls=c["TLS_VERIFY"])

    return connect


class UserThread(threading.Thread):
    def __init__(self, uid: int, version: int, factory=None):
        super().__init__(daemon=True, name=f"mail-u{uid}")
        self.uid, self.version, self.factory = uid, version, factory
        self.worker = None

    def run(self):
        from .smtp import SmtpSender
        from .worker import Worker

        try:
            with tenancy.use(self.uid):
                if self.factory:
                    self.worker = self.factory()
                else:
                    self.worker = Worker(make_connect(), SmtpSender())
                self.worker.run_forever()
        except Exception:  # noqa: BLE001
            log.exception("mail worker for user %s stopped", self.uid)
        finally:
            connections.close_all()

    def stop(self):
        if self.worker is not None:
            self.worker.shutdown()


class Supervisor:
    def __init__(self, factory=None):
        self.threads: dict[int, UserThread] = {}
        self.stopping = threading.Event()
        self.factory = factory  # tests/demo: uid -> Worker

    def scan(self) -> None:
        seen = set()
        for user in User.objects.filter(is_active=True).order_by("id"):
            try:
                want = wanted_version(user)
            except Exception:  # noqa: BLE001 - one broken account mustn't stop the others
                log.exception("can't read mail settings of user %s", user.id)
                want = None
            seen.add(user.id)
            t = self.threads.get(user.id)
            if t and (want is None or t.version != want or not t.is_alive()):
                t.stop()
                self.threads.pop(user.id, None)
                t = None
            if want is not None and t is None:
                f = (lambda uid=user.id: self.factory(uid)) if self.factory else None
                t = UserThread(user.id, want, f)
                self.threads[user.id] = t
                t.start()
                log.info("mail worker started for user %s", user.id)
        for uid in list(self.threads):
            if uid not in seen:  # deleted or disabled account
                self.threads.pop(uid).stop()
        connections.close_all()

    def run_forever(self) -> None:
        while not self.stopping.is_set():
            try:
                self.scan()
            except Exception:  # noqa: BLE001
                log.exception("mail supervisor scan failed")
            self.stopping.wait(SCAN_SECONDS)
        self.stop_all()

    def stop_all(self) -> None:
        for t in self.threads.values():
            t.stop()
        for t in self.threads.values():
            t.join(timeout=10)
        self.threads.clear()
