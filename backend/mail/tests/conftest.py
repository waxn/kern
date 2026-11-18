import json
import time

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts import site, totp
from kern import secretbox
from mail import account
from mail.imap.fake import FakeMailServer, FakeSender
from mail.models import MailAccount
from mail.outbox import Executor
from mail.sync import SyncEngine
from mail.testing import corpus

PASSWORD = "correct horse battery staple 42"
ME = corpus.ME


@pytest.fixture(autouse=True)
def _fresh(settings, tmp_path, db):
    from mail.pipeline import stages

    settings.MAIL = {}
    settings.DATA_DIR = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    stages._contact_cache.clear()
    account._cache.clear()
    secretbox.reset_for_tests()
    # The user's mail account: the corpus is addressed to ME.
    MailAccount.objects.create(pk=1, address=ME, imap_host="imap.test", smtp_host="smtp.test",
                               authserv_id=corpus.AUTHSERV, enabled=True,
                               password_enc=secretbox.encrypt("secret"))
    yield
    secretbox.reset_for_tests()


@pytest.fixture
def server():
    return FakeMailServer()


@pytest.fixture
def engine(server):
    return SyncEngine(server)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def executor(server, sender):
    return Executor(server, sender)


@pytest.fixture
def loaded(db, server, engine):
    """The full messy corpus, delivered and synced."""
    for item in corpus.build():
        server.deliver(item.folder, item.raw, item.flags, item.date)
    engine.sync_all()
    return server


@pytest.fixture
def user(db):
    site.mark_setup_complete()
    u = get_user_model().objects.create_user("me", password=PASSWORD)
    secret, _ = totp.start_setup(u)
    totp.TOTPDevice.objects.filter(user=u).update(confirmed=True)
    u._totp_secret = secret
    return u


def current_code(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(time.time() + offset * 30)


def _path(p: str) -> str:
    # Mail tests were written against Manifest's /api/...; Kern serves mail under /api/mail/.
    if p.startswith("/api/") and not p.startswith(("/api/mail/", "/api/auth", "/api/site", "/api/tasks", "/api/settings")):
        return "/api/mail/" + p[len("/api/"):]
    return p


class ApiClient:
    def __init__(self, client: Client):
        self.c = client

    def _kw(self):
        return {"HTTP_X_KERN": "1", "HTTP_SEC_FETCH_SITE": "same-origin"}

    def get(self, path, **params):
        return self.c.get(_path(path), params)

    def post(self, path, data=None):
        return self.c.post(_path(path), json.dumps(data or {}), content_type="application/json", **self._kw())

    def patch(self, path, data=None):
        return self.c.patch(_path(path), json.dumps(data or {}), content_type="application/json", **self._kw())

    def put(self, path, data=None):
        return self.c.put(_path(path), json.dumps(data or {}), content_type="application/json", **self._kw())

    def delete(self, path):
        return self.c.delete(_path(path), **self._kw())

    def upload(self, path, files):
        return self.c.post(_path(path), {"file": files}, **self._kw())


@pytest.fixture
def anon(db):
    site.mark_setup_complete()
    return ApiClient(Client())


@pytest.fixture
def api(user):
    api = ApiClient(Client())
    r = api.post("/api/auth/login", {"username": "me", "password": PASSWORD, "code": current_code(user._totp_secret)})
    assert r.status_code == 200, r.content
    return api
