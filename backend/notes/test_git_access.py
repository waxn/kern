"""Per-repository access tokens and public repositories (owner-qualified git URLs)."""
import os
import subprocess as sp
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.test import LiveServerTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import GitToken

from .test_git_hosting import GitRoot
from .tests import TEST_PASSWORD, basic


class _Live(GitRoot, LiveServerTestCase):
    def git(self, *args, cwd=None, ok=True):
        env = {"PATH": os.environ["PATH"], "HOME": self.git_root, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
               "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com"}
        r = sp.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
        if ok is not None:
            self.assertEqual(r.returncode == 0, ok, r.stderr)
        return r

    def url(self, path, cred=None):
        base = self.live_server_url
        if cred:
            base = base.replace("://", f"://{cred}@")
        return f"{base}/git/{path}"

    def make_work(self):
        work = tempfile.mkdtemp(dir=self.git_root, prefix="work-")
        self.git("init", "-q", "-b", "main", cwd=work)
        with open(os.path.join(work, "a.txt"), "w") as f:
            f.write("hello\n")
        self.git("add", "-A", cwd=work)
        self.git("commit", "-qm", "First", cwd=work)
        return work

    def token(self, repo, scope="read", label="ci", days=None):
        r = self.c.post(f"/api/git/repos/{repo}/tokens",
                        {"label": label, "scope": scope, "expires_days": days}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def mkrepo(self, name):
        self.assertEqual(self.c.post("/api/git/repos", {"name": name}, format="json").status_code, 201)


@override_settings(STATIC_URL="/static/")
class GitTokenTests(_Live):
    def setUp(self):
        super().setUp()
        self.mkrepo("site")
        self.work = self.make_work()
        self.git("push", "-q", self.url("site.git", f"tester:{TEST_PASSWORD}"), "main", cwd=self.work)

    def test_read_and_write_scope(self):
        rd, wr = self.token("site", "read"), self.token("site", "write", "deploy")
        self.assertTrue(rd["token"].startswith(f"kern_{rd['id']}_"))
        clone = os.path.join(self.git_root, "c1")
        self.git("clone", "-q", self.url("tester/site.git", f"x:{rd['token']}"), clone)
        self.assertTrue(os.path.isfile(os.path.join(clone, "a.txt")))
        with open(os.path.join(self.work, "b.txt"), "w") as f:
            f.write("b\n")
        self.git("add", "-A", cwd=self.work)
        self.git("commit", "-qm", "Second", cwd=self.work)
        r = self.git("push", self.url("tester/site.git", f"x:{rd['token']}"), "main", cwd=self.work, ok=False)
        self.assertIn("read-only", r.stderr)
        r = APIClient().get("/git/tester/site.git/info/refs?service=git-receive-pack",
                            HTTP_AUTHORIZATION=basic("x", rd["token"]))
        self.assertEqual(r.status_code, 403)
        self.git("push", "-q", self.url("tester/site.git", f"anyone:{wr['token']}"), "main", cwd=self.work)
        self.assertEqual(len(self.c.get("/api/git/repos/site/commits").json()["commits"]), 2)
        # last-used is recorded and the secret is never listed again.
        listed = self.c.get("/api/git/repos/site/tokens").json()
        self.assertEqual({t["label"] for t in listed}, {"ci", "deploy"})
        self.assertTrue(all(t["last_used"] for t in listed))
        self.assertNotIn("token", listed[0])
        self.assertNotIn(wr["token"].split("_", 2)[2], str(GitToken.objects.values_list("secret_hash", flat=True)))

    def test_token_is_bound_to_its_repo_and_owner(self):
        self.mkrepo("other")
        t = self.token("site", "write")["token"]
        c = APIClient()
        for path in ("tester/other.git", "nobody/site.git"):
            r = c.get(f"/git/{path}/info/refs?service=git-upload-pack", HTTP_AUTHORIZATION=basic("x", t))
            self.assertEqual(r.status_code, 401, path)
        # A second user in the same (test) database cannot be reached with it either.
        User.objects.create_user("mallory", password="mallory-password-1")
        r = c.get("/git/mallory/site.git/info/refs?service=git-upload-pack", HTTP_AUTHORIZATION=basic("x", t))
        self.assertEqual(r.status_code, 401)
        # Tokens do not work on the legacy URL form.
        r = c.get("/git/site.git/info/refs?service=git-upload-pack", HTTP_AUTHORIZATION=basic("tester", t))
        self.assertEqual(r.status_code, 401)
        # A wrong secret for a real id fails; the owner's tokens only list through their own session.
        bad = t[:-3] + ("aaa" if not t.endswith("aaa") else "bbb")
        r = c.get("/git/tester/site.git/info/refs?service=git-upload-pack", HTTP_AUTHORIZATION=basic("x", bad))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(c.get("/api/git/repos/site/tokens").status_code, 401)

    def test_expiry_and_revocation(self):
        t = self.token("site", "read", days=30)
        self.assertTrue(t["expires"])
        url = "/git/tester/site.git/info/refs?service=git-upload-pack"
        auth = basic("x", t["token"])
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=auth).status_code, 200)
        GitToken.objects.filter(id=t["id"]).update(expires=GitToken.objects.get(id=t["id"]).created)
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=auth).status_code, 401)
        self.assertTrue(self.c.get("/api/git/repos/site/tokens").json()[0]["expired"])

        t2 = self.token("site", "read", "gone")
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=basic("x", t2["token"])).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/git/repos/site/tokens/{t2['id']}").status_code, 204)
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=basic("x", t2["token"])).status_code, 401)
        self.assertEqual(self.c.delete(f"/api/git/repos/site/tokens/{t2['id']}").status_code, 404)

    def test_deleting_repo_revokes_tokens(self):
        self.token("site", "write")
        self.assertEqual(GitToken.objects.count(), 1)
        self.c.delete("/api/git/repos/site")
        self.assertEqual(GitToken.objects.count(), 0)

    def test_failures_are_throttled(self):
        t = self.token("site", "read")
        url = "/git/tester/site.git/info/refs?service=git-upload-pack"
        bad = basic("x", f"kern_{t['id']}_" + "z" * 43)
        for _ in range(10):
            self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=bad).status_code, 401)
        # Locked now, even for the right secret.
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION=basic("x", t["token"])).status_code, 401)

    def test_validation(self):
        post = lambda d: self.c.post("/api/git/repos/site/tokens", d, format="json").status_code
        self.assertEqual(post({"label": "", "scope": "read"}), 400)
        self.assertEqual(post({"label": "x", "scope": "admin"}), 400)
        self.assertEqual(post({"label": "x", "scope": "read", "expires_days": 7}), 400)
        self.assertEqual(self.c.post("/api/git/repos/nope/tokens", {"label": "x"}, format="json").status_code, 404)

    def test_pusher_label_token(self):
        # The push is attributed to the token's label, not to the account.
        wr = self.token("site", "write", "my ci")
        seen = []
        from . import views_git
        real = views_git._git_http

        def spy(request, name, rest, uid, remote_user, pusher):
            seen.append(pusher)
            return real(request, name, rest, uid, remote_user, pusher)
        with mock.patch.object(views_git, "_git_http", spy):
            APIClient().get("/git/tester/site.git/info/refs?service=git-receive-pack",
                            HTTP_AUTHORIZATION=basic("x", wr["token"]))
        self.assertEqual(seen, ["token:my ci"])


@override_settings(STATIC_URL="/static/")
class GitPublicTests(_Live):
    def setUp(self):
        super().setUp()
        self.mkrepo("site")
        self.work = self.make_work()
        self.git("push", "-q", self.url("site.git", f"tester:{TEST_PASSWORD}"), "main", cwd=self.work)

    def test_private_repo_refuses_anonymous(self):
        self.assertFalse(self.c.get("/api/git/repos/site").json()["public"])
        r = self.git("clone", "-q", self.url("tester/site.git"), os.path.join(self.git_root, "c"), ok=False)
        self.assertIn("could not read Username", r.stderr)  # git got a 401 challenge
        self.assertEqual(APIClient().get("/git/tester/site.git/info/refs?service=git-upload-pack").status_code, 401)
        self.assertEqual(APIClient().get("/git/nobody/nope.git/info/refs?service=git-upload-pack").status_code, 401)

    def test_public_repo_allows_anonymous_clone_not_push(self):
        r = self.c.patch("/api/git/repos/site", {"public": True}, format="json")
        self.assertTrue(r.json()["public"])
        self.assertEqual(r.json()["owner"], "tester")
        self.assertTrue(self.c.get("/api/git/repos").json()[0]["public"])
        clone = os.path.join(self.git_root, "c")
        self.git("clone", "-q", self.url("TESTER/site.git"), clone)  # owner name is case-insensitive
        self.assertTrue(os.path.isfile(os.path.join(clone, "a.txt")))
        self.git("fetch", "-q", cwd=clone)
        with open(os.path.join(clone, "n.txt"), "w") as f:
            f.write("n\n")
        self.git("add", "-A", cwd=clone)
        self.git("commit", "-qm", "anon", cwd=clone)
        self.git("push", "origin", "main", cwd=clone, ok=False)
        c = APIClient()
        self.assertEqual(c.get("/git/tester/site.git/info/refs?service=git-receive-pack").status_code, 401)
        self.assertEqual(c.post("/git/tester/site.git/git-receive-pack", "x",
                                content_type="application/x-git-receive-pack-request").status_code, 401)
        # Another account's password is no better than anonymous for writes, and good enough for reads.
        User.objects.create_user("mallory", password="mallory-password-1")
        other = basic("mallory", "mallory-password-1")
        self.assertEqual(c.get("/git/tester/site.git/info/refs?service=git-upload-pack",
                               HTTP_AUTHORIZATION=other).status_code, 200)
        self.assertEqual(c.get("/git/tester/site.git/info/refs?service=git-receive-pack",
                               HTTP_AUTHORIZATION=other).status_code, 404)
        # Back to private.
        self.c.patch("/api/git/repos/site", {"public": False}, format="json")
        self.assertEqual(c.get("/git/tester/site.git/info/refs?service=git-upload-pack").status_code, 401)

    def test_public_respects_site_switch(self):
        from accounts import site
        self.c.patch("/api/git/repos/site", {"public": True}, format="json")
        site.update({"allow_git": False})
        r = APIClient().get("/git/tester/site.git/info/refs?service=git-upload-pack")
        self.assertEqual(r.status_code, 403)

    def test_inactive_owner_and_old_form_unchanged(self):
        self.c.patch("/api/git/repos/site", {"public": True}, format="json")
        # The legacy URL never serves anonymously, public or not.
        self.assertEqual(APIClient().get("/git/site.git/info/refs?service=git-upload-pack").status_code, 401)
        r = APIClient().get("/git/site.git/info/refs?service=git-upload-pack", HTTP_AUTHORIZATION=basic())
        self.assertEqual(r.status_code, 200)
        # The owner can use the qualified URL with their password too.
        r = APIClient().get("/git/tester/site.git/info/refs?service=git-receive-pack", HTTP_AUTHORIZATION=basic())
        self.assertEqual(r.status_code, 200)
        User.objects.filter(username="tester").update(is_active=False)
        self.assertEqual(APIClient().get("/git/tester/site.git/info/refs?service=git-upload-pack").status_code, 401)


class GitCaddyTests(TestCase):
    def test_caddy_routes_owner_form(self):
        import re
        from pathlib import Path
        conf = (Path(__file__).resolve().parents[2] / "frontend" / "Caddyfile").read_text()
        pat = re.search(r"@git path_regexp (\S+)", conf).group(1)
        for p in ("/git/x.git/info/refs", "/git/tester/x.git/info/refs"):
            self.assertTrue(re.match(pat, p), p)
        self.assertFalse(re.match(pat, "/git/tester"))
