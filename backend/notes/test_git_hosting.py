"""Git hosting beyond browsing: push events, protected branches, archives.

``GitLive`` is a base class for tests that push and clone with a real git client; feature tests
(CI, tokens, SSH, mirrors…) build on it in their own ``test_git_*.py`` files."""
import io
import os
import shutil
import subprocess
import tempfile
import zipfile

from django.test import LiveServerTestCase, TestCase, override_settings

from notes import gitevents
from notes.tests import TEST_PASSWORD, authed


class GitRoot:
    def setUp(self):
        super().setUp()
        self.git_root = tempfile.mkdtemp(prefix="kern-git-test-")
        self._override = override_settings(KERN_GIT_ROOT=self.git_root)
        self._override.enable()
        self.c = authed()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.git_root, ignore_errors=True)
        super().tearDown()


@override_settings(STATIC_URL="/static/")  # the live server's static handler needs one
class GitLive(GitRoot, LiveServerTestCase):
    """A live server plus helpers to make commits and push them with the real git client."""

    def git_env(self):
        return {"PATH": os.environ["PATH"], "HOME": self.git_root, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
                "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com"}

    def run_git(self, *args, cwd=None, ok=True):
        r = subprocess.run(["git", *args], cwd=cwd, env=self.git_env(), capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def url(self, repo, user="tester", pw=TEST_PASSWORD):
        return f"{self.live_server_url.replace('://', f'://{user}:{pw}@')}/git/{repo}.git"

    def make_repo(self, name):
        r = self.c.post("/api/git/repos", {"name": name}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def workdir(self, files=None, msg="First"):
        work = tempfile.mkdtemp(dir=self.git_root, prefix="work-")
        self.run_git("init", "-q", "-b", "main", cwd=work)
        self.commit(work, files or {"README.md": "# Hi\n"}, msg)
        return work

    def commit(self, work, files, msg="Change"):
        for rel, content in files.items():
            p = os.path.join(work, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
        self.run_git("add", "-A", cwd=work)
        self.run_git("commit", "-qm", msg, cwd=work)
        return self.run_git("rev-parse", "HEAD", cwd=work).stdout.strip()


class PushEventTests(GitLive):
    def setUp(self):
        super().setUp()
        self.events = []
        gitevents._loaded = True  # listeners from other modules stay out of these tests
        self._saved = list(gitevents._listeners)
        gitevents._listeners[:] = [self.events.append]

    def tearDown(self):
        gitevents._listeners[:] = self._saved
        super().tearDown()

    def test_listeners_get_ref_updates(self):
        self.make_repo("ev")
        work = self.workdir()
        sha = self.run_git("rev-parse", "HEAD", cwd=work).stdout.strip()
        self.run_git("tag", "v1", cwd=work)
        self.run_git("push", "-q", self.url("ev"), "main", "--tags", cwd=work)
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual((ev.repo, ev.pusher, ev.via), ("ev", "tester", "http"))
        self.assertEqual({(u.ref, u.old, u.new) for u in ev.updates},
                         {("refs/heads/main", gitevents.ZERO, sha), ("refs/tags/v1", gitevents.ZERO, sha)})
        self.assertTrue(ev.updates[0].created)
        # A push that changes nothing tells nobody.
        self.run_git("push", "-q", self.url("ev"), "main", cwd=work)
        self.assertEqual(len(self.events), 1)
        self.run_git("push", "-q", self.url("ev"), ":refs/tags/v1", cwd=work)
        self.assertTrue(self.events[1].updates[0].deleted)
        self.assertEqual(self.events[1].updates[0].tag, "v1")


class ProtectedBranchTests(GitLive):
    def test_force_push_and_delete_are_refused(self):
        self.make_repo("prot")
        work = self.workdir()
        self.commit(work, {"a.txt": "1\n"})
        self.run_git("push", "-q", self.url("prot"), "main", "main:feature", cwd=work)
        r = self.c.patch("/api/git/repos/prot", {"protected": [{"pattern": "main"}, {"pattern": "rel/*", "allow_force": True}]},
                         format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["protected"][0], {"pattern": "main", "allow_force": False, "allow_delete": False})

        self.run_git("reset", "-q", "--hard", "HEAD~1", cwd=work)
        self.commit(work, {"b.txt": "2\n"}, "Rewritten")
        r = self.run_git("push", "-f", self.url("prot"), "main", cwd=work, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot be force-pushed", r.stderr)
        r = self.run_git("push", self.url("prot"), ":main", cwd=work, ok=False)
        self.assertIn("cannot be deleted", r.stderr)
        # Unprotected branches are unaffected; fast-forwards to protected ones still work.
        self.run_git("push", "-q", "-f", self.url("prot"), "main:feature", cwd=work)
        self.run_git("push", "-q", self.url("prot"), ":feature", cwd=work)
        self.run_git("fetch", "-q", self.url("prot"), "main", cwd=work)
        self.run_git("reset", "-q", "--hard", "FETCH_HEAD", cwd=work)
        self.commit(work, {"c.txt": "3\n"})
        self.run_git("push", "-q", self.url("prot"), "main", cwd=work)

    def test_rule_validation(self):
        self.c.post("/api/git/repos", {"name": "v"}, format="json")
        for bad in ["nope", [{"pattern": ""}], [{"pattern": "-x"}], [{"pattern": "a b"}], [3]]:
            self.assertEqual(self.c.patch("/api/git/repos/v", {"protected": bad}, format="json").status_code, 400, bad)
        r = self.c.patch("/api/git/repos/v", {"protected": ["main", "main"]}, format="json")
        self.assertEqual([p["pattern"] for p in r.json()["protected"]], ["main"])


class ArchiveTests(GitLive):
    def test_zip_and_tarball(self):
        self.make_repo("arc")
        work = self.workdir({"README.md": "# A\n", "src/x.py": "x = 1\n"})
        self.run_git("push", "-q", self.url("arc"), "main", cwd=work)
        r = self.c.get("/api/git/repos/arc/archive", {"format": "zip"})
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="arc-main.zip"', r["Content-Disposition"])
        names = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content))).namelist()
        self.assertIn("arc-main/src/x.py", names)
        r = self.c.get("/api/git/repos/arc/archive", {"format": "tar.gz", "ref": "main"})
        self.assertEqual(b"".join(r.streaming_content)[:2], b"\x1f\x8b")
        self.assertEqual(self.c.get("/api/git/repos/arc/archive", {"format": "rar"}).status_code, 400)
        self.assertEqual(self.c.get("/api/git/repos/arc/archive", {"ref": "--output=/tmp/x"}).status_code, 404)


class NoPushHooksFromRepos(GitRoot, TestCase):
    def test_hooks_path_is_kerns_own(self):
        from notes import gitrepo as g
        self.assertEqual(g.SAFE_CONFIG["core.hooksPath"], str(g.HOOKS_DIR))
        self.assertTrue(os.access(g.HOOKS_DIR / "pre-receive", os.X_OK))
