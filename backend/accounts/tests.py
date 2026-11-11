import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts import site
from kern import tenancy

PW = "correct horse battery"


def client(user=None):
    c = APIClient(HTTP_X_KERN="1")
    if user:
        c.force_login(user)
    return c


class SetupTests(TestCase):
    def test_site_info_is_public_and_says_setup_needed(self):
        j = client().get("/api/site").json()
        self.assertTrue(j["needs_setup"])
        self.assertIsNone(j["user"])

    def test_setup_needs_the_code_and_a_strong_password(self):
        c = client()
        body = {"code": "WRONG", "username": "admin", "password": PW}
        self.assertEqual(c.post("/api/setup", body, format="json").status_code, 403)
        body["code"] = site.setup_code()
        body["password"] = "12345678"
        self.assertEqual(c.post("/api/setup", body, format="json").status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_setup_creates_admin_signs_in_and_locks_itself(self):
        c = client()
        r = c.post("/api/setup", {
            "code": site.setup_code().lower(), "username": "Admin", "password": PW,
            "site": {"site_name": "My Kern", "landing_enabled": True, "signup_mode": "approval", "allow_git": False},
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertFalse(j["needs_setup"])
        self.assertEqual((j["site_name"], j["landing_enabled"], j["signup_mode"], j["allow_git"]),
                         ("My Kern", True, "approval", False))
        self.assertTrue(j["user"]["is_admin"])
        self.assertEqual(c.get("/api/tree").status_code, 200)  # signed in by setup
        again = client().post("/api/setup", {"code": "x", "username": "evil", "password": PW}, format="json")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(User.objects.count(), 1)

    def test_login_before_setup_is_refused(self):
        r = client().post("/api/auth/login", {"username": "a", "password": "b"}, format="json")
        self.assertEqual(r.status_code, 409)


def fake_backup(path, account=None):
    """A minimal valid Kern backup zip (the restore itself is mocked in these tests)."""
    import json
    import sqlite3
    import zipfile
    db = str(path) + ".db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE notes_document (id integer)")
    con.commit()
    con.close()
    with zipfile.ZipFile(path, "w") as z:
        z.write(db, "kern.sqlite3")
        z.writestr("manifest.json", json.dumps({"app": "kern", "format": 2, "counts": {"documents": 3},
                                                "contents": {"account": account is not None}}))
        if account is not None:
            z.writestr("account.json", json.dumps(account))
    return path


class SetupRestoreTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kern-setup-restore-"))
        from unittest import mock
        from notes import backup
        self.restore = mock.patch.object(backup, "restore", return_value={
            "restored": {"counts": {"documents": 3}, "created_at": "2026-01-01T00:00:00Z"},
            "contents": {"database": True}, "safety_backup": None})
        self.mock = self.restore.start()

    def tearDown(self):
        self.restore.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, zip_path, **fields):
        with open(zip_path, "rb") as f:
            return client().post("/api/setup/restore", {"code": site.setup_code(), "file": f, **fields}, format="multipart")

    def test_restores_the_account_and_server_settings_from_the_backup(self):
        from django.contrib.auth.hashers import make_password
        acct = {"username": "linus", "email": "l@example.org", "password": make_password(PW), "is_admin": True,
                "site": {"site_name": "Home Kern", "signup_mode": "approval", "landing_enabled": True, "allow_git": False}}
        r = self.post(fake_backup(self.tmp / "b.zip", acct))
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual(j["user"]["username"], "linus")
        self.assertTrue(j["user"]["is_admin"])
        self.assertEqual((j["site_name"], j["signup_mode"], j["landing_enabled"], j["allow_git"]),
                         ("Home Kern", "approval", True, False))
        self.assertEqual(j["restored"]["counts"], {"documents": 3})
        self.assertFalse(self.mock.call_args.kwargs["safety"])  # nothing to keep on a new server
        self.assertTrue(site.setup_complete())
        # The old password works; setup is locked now.
        self.assertEqual(client().post("/api/auth/login", {"username": "linus", "password": PW}, format="json").status_code, 200)
        self.assertEqual(self.post(fake_backup(self.tmp / "c.zip", acct)).status_code, 409)

    def test_wrong_code_and_not_a_backup_are_refused(self):
        zp = fake_backup(self.tmp / "b.zip", {"username": "linus", "password": "x"})
        with open(zp, "rb") as f:
            r = client().post("/api/setup/restore", {"code": "WRONG", "file": f}, format="multipart")
        self.assertEqual(r.status_code, 403)
        junk = self.tmp / "junk.zip"
        junk.write_bytes(b"not a zip")
        self.assertEqual(self.post(junk).status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_old_backups_ask_for_an_account(self):
        zp = fake_backup(self.tmp / "old.zip")
        r = self.post(zp)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["need_account"])
        self.assertFalse(User.objects.exists())
        r = self.post(zp, username="admin", password=PW)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["user"]["username"], "admin")

    def test_a_failed_restore_leaves_the_server_unset(self):
        from django.contrib.auth.hashers import make_password
        self.mock.side_effect = ValueError("The database in this backup is damaged.")
        r = self.post(fake_backup(self.tmp / "b.zip", {"username": "linus", "password": make_password(PW)}))
        self.assertEqual(r.status_code, 400)
        self.assertIn("damaged", r.json()["detail"])
        self.assertFalse(User.objects.exists())
        self.assertFalse(site.setup_complete())


class AuthTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password=PW, is_staff=True, is_superuser=True)
        site.mark_setup_complete()

    def test_api_needs_a_session(self):
        for path in ("/api/tree", "/api/settings", "/api/admin/users", "/api/git/repos"):
            self.assertEqual(client().get(path).status_code, 401, path)
        self.assertEqual(client().get("/api/health").json(), {"ok": True})  # minimal when signed out

    def test_site_info_knows_the_signed_in_user(self):
        c = client()
        c.post("/api/auth/login", {"username": "admin", "password": PW}, format="json")
        self.assertEqual(c.get("/api/site").json()["user"]["username"], "admin")
        self.assertEqual(c.get("/api/health").json()["ok"], True)
        c.post("/api/auth/logout", {}, format="json")
        self.assertIsNone(c.get("/api/site").json()["user"])

    def test_login_and_logout(self):
        c = client()
        self.assertEqual(c.post("/api/auth/login", {"username": "admin", "password": "nope"}, format="json").status_code, 401)
        r = c.post("/api/auth/login", {"username": "ADMIN", "password": PW}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["username"], "admin")
        self.assertEqual(c.get("/api/tree").status_code, 200)
        c.post("/api/auth/logout", {}, format="json")
        self.assertEqual(c.get("/api/tree").status_code, 401)

    def test_repeated_failures_lock_the_account(self):
        c = client()
        for _ in range(8):
            c.post("/api/auth/login", {"username": "admin", "password": "bad"}, format="json")
        r = c.post("/api/auth/login", {"username": "admin", "password": PW}, format="json")
        self.assertEqual(r.status_code, 429)

    def test_writes_need_header_and_same_origin(self):
        c = client(self.admin)
        self.assertEqual(APIClient().post("/api/documents", {}, format="json").status_code, 403)
        r = c.post("/api/documents", {}, format="json", HTTP_ORIGIN="https://evil.example")
        self.assertEqual(r.status_code, 403)
        r = c.post("/api/documents", {}, format="json", HTTP_ORIGIN="http://testserver")
        self.assertEqual(r.status_code, 201)
        # Browsers that send Sec-Fetch-Site are judged by it, whatever the Host header says.
        r = c.post("/api/documents", {}, format="json", HTTP_SEC_FETCH_SITE="cross-site", HTTP_ORIGIN="http://testserver")
        self.assertEqual(r.status_code, 403)
        r = c.post("/api/documents", {}, format="json", HTTP_SEC_FETCH_SITE="same-site")
        self.assertEqual(r.status_code, 403)
        r = c.post("/api/documents", {}, format="json", HTTP_SEC_FETCH_SITE="same-origin", HTTP_ORIGIN="http://other-proxy-host")
        self.assertEqual(r.status_code, 201)

    def test_signup_modes(self):
        c = client()
        body = {"username": "newbie", "password": "a long enough phrase"}
        self.assertEqual(c.post("/api/auth/signup", body, format="json").status_code, 403)  # closed
        site.update({"signup_mode": "approval"})
        r = c.post("/api/auth/signup", body, format="json")
        self.assertEqual((r.status_code, r.json()), (202, {"pending": True}))
        u = User.objects.get(username="newbie")
        self.assertFalse(u.is_active)
        r = c.post("/api/auth/login", {"username": "newbie", "password": body["password"]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client().get("/api/tree").status_code, 401)
        # An admin approves.
        a = client(self.admin)
        self.assertEqual(a.patch(f"/api/admin/users/{u.id}", {"is_active": True}, format="json").status_code, 200)
        self.assertEqual(c.post("/api/auth/login", {"username": "newbie", "password": body["password"]}, format="json").status_code, 200)
        site.update({"signup_mode": "open"})
        r = client().post("/api/auth/signup", {"username": "other", "password": "a long enough phrase"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(client().post("/api/auth/signup", {"username": "OTHER", "password": "a long enough phrase"}, format="json").status_code, 400)

    def test_admin_only_endpoints(self):
        user = User.objects.create_user("bob", password=PW)
        b = client(user)
        self.assertEqual(b.get("/api/admin/users").status_code, 403)
        self.assertEqual(b.patch("/api/admin/site", {"signup_mode": "open"}, format="json").status_code, 403)
        self.assertEqual(b.patch(f"/api/admin/users/{self.admin.id}", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(client(self.admin).get("/api/admin/users").status_code, 200)

    def test_last_admin_is_protected(self):
        a = client(self.admin)
        self.assertEqual(a.patch(f"/api/admin/users/{self.admin.id}", {"is_admin": False}, format="json").status_code, 400)
        self.assertEqual(a.delete(f"/api/admin/users/{self.admin.id}").status_code, 400)
        other = User.objects.create_user("second", password=PW, is_staff=True)
        self.assertEqual(a.patch(f"/api/admin/users/{other.id}", {"is_admin": False}, format="json").status_code, 200)

    def test_change_password_logs_out_other_sessions(self):
        mine, other = client(), client()
        for c in (mine, other):
            c.post("/api/auth/login", {"username": "admin", "password": PW}, format="json")
        r = mine.post("/api/auth/password", {"current": "wrong", "new": "brand new passphrase"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = mine.post("/api/auth/password", {"current": PW, "new": "brand new passphrase"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mine.get("/api/tree").status_code, 200)
        self.assertEqual(other.get("/api/tree").status_code, 401)

    def test_git_hosting_can_be_switched_off(self):
        site.update({"allow_git": False})
        r = APIClient().get("/git/x.git/info/refs?service=git-upload-pack")
        self.assertEqual(r.status_code, 403)


class IsolationTests(TransactionTestCase):
    """The real multi-user layout: one database and one media folder per user."""


    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kern-tenancy-"))
        self._o = override_settings(KERN_TESTING=False, DATA_DIR=self.tmp, MEDIA_ROOT=self.tmp / "unused")
        self._o.enable()
        site.mark_setup_complete()
        self.alice = User.objects.create_user("alice", password=PW)
        self.bob = User.objects.create_user("bob", password=PW)
        # Django's test guard only knows the databases that existed when the class was set up.
        extra = {tenancy.alias_of(i) for i in range(1, 12)}
        type(self).databases = frozenset(type(self).databases) | extra

    def tearDown(self):
        for i in range(1, 12):
            tenancy.forget_db(i)
        type(self).databases = frozenset({"default"})  # so the end-of-test flush skips the user databases
        self._o.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_users_cannot_see_each_others_data(self):
        a, b = client(self.alice), client(self.bob)
        doc = a.post("/api/documents", {"title": "Alice's diary"}, format="json").json()
        up = a.post("/api/files", {"file": __import__("django.core.files.uploadedfile", fromlist=["x"]).SimpleUploadedFile("n.txt", b"private", "text/plain")}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        url = up.json()["url"]
        self.assertTrue((self.tmp / "users" / str(self.alice.id) / "kern.sqlite3").exists())
        self.assertTrue((self.tmp / "users" / str(self.alice.id) / "media").exists())
        # Alice sees her page and her file; Bob sees neither, by list or by id or by URL.
        self.assertEqual([d["title"] for d in a.get("/api/tree").json()], ["Alice's diary"])
        self.assertEqual(a.get(url).status_code, 200)
        self.assertEqual(b.get("/api/tree").json(), [])
        self.assertEqual(b.get(f"/api/documents/{doc['id']}").status_code, 404)
        self.assertEqual(b.patch(f"/api/documents/{doc['id']}", {"title": "pwned"}, format="json").status_code, 404)
        self.assertEqual(b.get("/api/library").json(), [])
        self.assertEqual(b.get(url).status_code, 404)
        self.assertEqual(b.get("/api/search", {"q": "diary"}).json().get("results", b.get("/api/search", {"q": "diary"}).json()), [])
        # Search, settings and backups are per user as well.
        a.patch("/api/settings", {"theme_x": 1}, format="json")
        self.assertNotIn("theme_x", b.get("/api/settings").json())
        self.assertEqual(b.get("/api/backups").json(), [])
        self.assertEqual(a.post("/api/backups").status_code, 201)
        self.assertEqual(len(a.get("/api/backups").json()), 1)
        self.assertEqual(b.get("/api/backups").json(), [])

    def test_deleting_a_user_removes_their_data(self):
        admin = User.objects.create_user("root", password=PW, is_staff=True)
        client(self.bob).post("/api/documents", {"title": "x"}, format="json")
        folder = self.tmp / "users" / str(self.bob.id)
        self.assertTrue(folder.exists())
        self.assertEqual(client(admin).delete(f"/api/admin/users/{self.bob.id}").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertFalse(User.objects.filter(username="bob").exists())
