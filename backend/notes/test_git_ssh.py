"""Git over SSH: the asyncssh server (notes/gitssh.py) driven by the real git and ssh clients, and the
key-management API. The server runs in-process on a random port."""
import asyncio
import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase

from accounts import site
from accounts.models import SSHKey
from notes import gitevents, gitssh
from notes.test_git_hosting import GitLive, GitRoot
from notes.tests import authed


def keygen(directory, name, kind="ed25519", bits=None):
    """Make a key pair with ssh-keygen; returns (private key path, public key line)."""
    path = os.path.join(directory, name)
    cmd = ["ssh-keygen", "-q", "-t", kind, "-N", "", "-C", f"{name}@test", "-f", path]
    if bits:
        cmd += ["-b", str(bits)]
    subprocess.run(cmd, check=True, capture_output=True)
    with open(path + ".pub") as f:
        return path, f.read().strip()


class KeyApiTests(GitRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.keys = self.enterContext(__import__("tempfile").TemporaryDirectory())

    def add(self, title, pub, **kw):
        return self.c.post("/api/git/ssh-keys", {"title": title, "key": pub, **kw}, format="json")

    def test_account_keys(self):
        _, pub = keygen(self.keys, "a")
        r = self.add("Laptop", pub)
        self.assertEqual(r.status_code, 201, r.content)
        k = r.json()
        self.assertEqual(k["title"], "Laptop")
        self.assertEqual(k["type"], "ssh-ed25519")
        self.assertTrue(k["fingerprint"].startswith("SHA256:"))
        self.assertFalse(k["read_only"])
        # The comment is dropped from what is stored.
        self.assertEqual(SSHKey.objects.get().public_key, " ".join(pub.split()[:2]))
        self.assertEqual([x["id"] for x in self.c.get("/api/git/ssh-keys").json()], [k["id"]])
        self.assertEqual(self.c.delete(f"/api/git/ssh-keys/{k['id']}").status_code, 204)
        self.assertEqual(self.c.get("/api/git/ssh-keys").json(), [])
        self.assertEqual(self.c.delete(f"/api/git/ssh-keys/{k['id']}").status_code, 404)

    def test_key_types(self):
        for kind, bits in (("ecdsa", 256), ("ecdsa", 521), ("rsa", 2048)):
            _, pub = keygen(self.keys, f"{kind}{bits}", kind, bits)
            self.assertEqual(self.add(kind, pub).status_code, 201, kind)

    def test_validation(self):
        priv, pub = keygen(self.keys, "a")
        _, short = keygen(self.keys, "short", "rsa", 1024)
        with open(priv) as f:
            private = f.read()
        for title, key, word in [
            ("x", "", "public key"),
            ("x", "not a key", "Unsupported"),
            ("x", "ssh-ed25519 AAAA", "valid"),
            ("x", "ssh-ed25519 !!!notbase64", "valid"),
            ("x", "ssh-dss AAAAB3NzaC1kc3MAAACBAP", "Unsupported"),
            ("x", short, "2048"),
            ("x", private, "private key"),
            ("x", pub + "\n" + pub, "single"),
            ("", pub, "title"),
        ]:
            r = self.add(title, key)
            self.assertEqual(r.status_code, 400, (key, r.content))
            self.assertIn(word, r.json()["detail"], key)
        self.assertEqual(SSHKey.objects.count(), 0)
        # A key whose body does not match its declared type.
        _, ec = keygen(self.keys, "ec", "ecdsa", 256)
        self.assertEqual(self.add("x", "ssh-ed25519 " + ec.split()[1]).status_code, 400)

    def test_a_key_is_registered_once_server_wide(self):
        _, pub = keygen(self.keys, "a")
        self.assertEqual(self.add("one", pub).status_code, 201)
        r = self.add("two", pub + " other-comment")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already registered", r.json()["detail"])
        other = User.objects.create_user("other", password="x-other-password")
        self.assertRaises(ValueError, __import__("accounts.sshkeys", fromlist=["add"]).add, other, "mine", pub)
        # ...also as a deploy key.
        self.c.post("/api/git/repos", {"name": "r"}, format="json")
        r = self.c.post("/api/git/repos/r/deploy-keys", {"title": "d", "key": pub}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_deploy_keys(self):
        self.c.post("/api/git/repos", {"name": "r"}, format="json")
        _, pub = keygen(self.keys, "d")
        r = self.c.post("/api/git/repos/r/deploy-keys", {"title": "CI", "key": pub, "read_only": True}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        k = r.json()
        self.assertTrue(k["read_only"])
        self.assertEqual(k["repo"], "r")
        self.assertEqual(len(self.c.get("/api/git/repos/r/deploy-keys").json()), 1)
        # Deploy keys are not account keys.
        self.assertEqual(self.c.get("/api/git/ssh-keys").json(), [])
        self.assertEqual(self.c.delete(f"/api/git/ssh-keys/{k['id']}").status_code, 404)
        self.assertEqual(self.c.get("/api/git/repos/nope/deploy-keys").status_code, 404)
        self.assertEqual(self.c.post("/api/git/repos/nope/deploy-keys", {"title": "x", "key": pub}, format="json").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/git/repos/r/deploy-keys/{k['id']}").status_code, 204)
        self.assertEqual(self.c.get("/api/git/repos/r/deploy-keys").json(), [])

    def test_deleting_a_repo_deletes_its_deploy_keys(self):
        self.c.post("/api/git/repos", {"name": "r"}, format="json")
        self.c.post("/api/git/repos", {"name": "keep"}, format="json")
        _, p1 = keygen(self.keys, "d1")
        _, p2 = keygen(self.keys, "d2")
        _, p3 = keygen(self.keys, "acct")
        self.c.post("/api/git/repos/r/deploy-keys", {"title": "a", "key": p1}, format="json")
        self.c.post("/api/git/repos/keep/deploy-keys", {"title": "b", "key": p2}, format="json")
        self.add("acct", p3)
        self.assertEqual(self.c.delete("/api/git/repos/r").status_code, 204)
        self.assertEqual(sorted(SSHKey.objects.values_list("title", flat=True)), ["acct", "b"])

    def test_config_reports_ssh(self):
        r = self.c.get("/api/git/config").json()
        self.assertEqual(r["ssh"]["enabled"], False)
        self.assertEqual(r["ssh"]["port"], 2222)
        self.assertEqual(r["ssh"]["host"], "testserver")
        gitssh.write_heartbeat(2222, "SHA256:abc")
        self.addCleanup(gitssh.heartbeat_path().unlink, missing_ok=True)
        r = self.c.get("/api/git/config").json()
        self.assertEqual(r["ssh"]["enabled"], True)
        self.assertEqual(r["ssh"]["fingerprint"], "SHA256:abc")
        with self.settings(ALLOWED_HOSTS=["*"]):
            old = os.environ.get("KERN_SSH_HOST"), os.environ.get("KERN_SSH_PORT")
            os.environ["KERN_SSH_HOST"], os.environ["KERN_SSH_PORT"] = "git.example.com", "2200"
            try:
                r = self.c.get("/api/git/config").json()
            finally:
                for k, v in zip(("KERN_SSH_HOST", "KERN_SSH_PORT"), old):
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual((r["ssh"]["host"], r["ssh"]["port"]), ("git.example.com", 2200))
        # A stale heartbeat means the service is not running.
        p = gitssh.heartbeat_path()
        p.write_text(json.dumps({"time": 1, "port": 2222, "fingerprint": "x"}))
        self.assertEqual(self.c.get("/api/git/config").json()["ssh"]["enabled"], False)


class SSHServerTests(GitLive):
    reset_sequences = True  # keep user ids small: accounts.tests.IsolationTests assumes ids below 12

    def setUp(self):
        super().setUp()
        self.keys = os.path.join(self.git_root, "keys")
        os.makedirs(self.keys)
        self.events = []
        gitevents._loaded = True  # listeners from other modules stay out of these tests
        self._saved = list(gitevents._listeners)
        gitevents._listeners[:] = [self.events.append]
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            hostkey = gitssh.load_host_key(Path(self.git_root) / "ssh_host_key")
            self.acceptor = self.loop.run_until_complete(gitssh.serve("127.0.0.1", 0, hostkey))
            ready.set()
            self.loop.run_forever()
            self.acceptor.close()
            self.loop.run_until_complete(self.acceptor.wait_closed())
            self.loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(self.loop), return_exceptions=True))
            self.loop.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.assertTrue(ready.wait(10))
        self.port = self.acceptor.get_port()
        self.key, pub = keygen(self.keys, "me")
        self.assertEqual(self.c.post("/api/git/ssh-keys", {"title": "laptop", "key": pub}, format="json").status_code, 201)
        self.ssh_key = self.key

    def run_git(self, *args, **kw):
        r = super().run_git(*args, **kw)
        self.settle()
        return r

    def tearDown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)
        gitevents._listeners[:] = self._saved
        super().tearDown()

    # -- helpers
    def ssh_args(self, key=None):
        return ["ssh", "-F", "/dev/null", "-i", key or self.ssh_key, "-p", str(self.port),
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]

    def git_env(self):
        return {**super().git_env(), "GIT_SSH_COMMAND": shlex.join(self.ssh_args())}

    def ssh_url(self, repo, user="git", owner=None):
        return f"ssh://{user}@127.0.0.1:{self.port}/{owner + '/' if owner else ''}{repo}.git"

    def settle(self):
        """Wait out the server's background bookkeeping (failure counting): the test database is shared
        in-memory SQLite, where a concurrent write from the server thread would lock out ours."""
        time.sleep(0.15)
        gitssh._pool.submit(lambda: None).result(10)

    def ssh(self, *remote, key=None, extra=()):
        r = self._ssh(*remote, key=key, extra=extra)
        self.settle()
        return r

    def _ssh(self, *remote, key=None, extra=()):
        return subprocess.run([*self.ssh_args(key), *extra, "git@127.0.0.1", *remote], capture_output=True,
                              text=True, timeout=30, stdin=subprocess.DEVNULL)

    def reaches_git(self, cmd, **kw):
        """Did this command get through sign-in and Kern's checks (git itself then ran)?"""
        r = self.ssh(cmd, **kw)
        return r.returncode != 255 and not r.stderr.startswith("Kern:")

    def add_key(self, title, repo, read_only):
        path, pub = keygen(self.keys, title.replace(" ", "-"))
        r = self.c.post(f"/api/git/repos/{repo}/deploy-keys", {"title": title, "key": pub, "read_only": read_only}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return path

    # -- tests
    def test_clone_and_push(self):
        self.make_repo("proj")
        work = self.workdir()
        sha = self.run_git("rev-parse", "HEAD", cwd=work).stdout.strip()
        self.run_git("push", "-q", self.ssh_url("proj"), "main", cwd=work)
        self.assertEqual(self.run_git("--git-dir", f"{self.git_root}/proj.git", "rev-parse", "main").stdout.strip(), sha)
        # The push listener fired once, over ssh, with the key as pusher.
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual((ev.via, ev.pusher, ev.repo), ("ssh", "key:laptop", "proj"))
        self.assertEqual([(u.ref, u.new, u.created) for u in ev.updates], [("refs/heads/main", sha, True)])
        self.assertEqual(ev.uid, User.objects.get(username="tester").id)
        # Clone it back, push a second commit from the clone.
        dest = os.path.join(self.git_root, "clone")
        self.run_git("clone", "-q", self.ssh_url("proj"), dest)
        self.assertTrue(os.path.exists(os.path.join(dest, "README.md")))
        sha2 = self.commit(dest, {"b.txt": "b\n"})
        self.run_git("push", "-q", cwd=dest)
        self.assertEqual(self.events[-1].updates[0].new, sha2)
        self.assertEqual(self.events[-1].updates[0].old, sha)
        # The server's bookkeeping ran as for HTTP pushes.
        self.assertTrue(SSHKey.objects.get().last_used)
        summary = self.c.get("/api/git/repos").json()[0]
        self.assertTrue(summary["last_push"])

    def test_path_forms(self):
        self.make_repo("proj")
        work = self.workdir()
        self.run_git("push", "-q", self.ssh_url("proj"), "main", cwd=work)
        for i, url in enumerate((self.ssh_url("proj"), self.ssh_url("proj", owner="tester"),
                                 self.ssh_url("proj", owner="TESTER"),
                                 f"git@127.0.0.1:proj.git".replace("git@127.0.0.1:", f"ssh://git@127.0.0.1:{self.port}/"))):
            self.run_git("clone", "-q", url, os.path.join(self.git_root, f"c{i}"))
        # The raw command forms git itself may send.
        for cmd in ("git-upload-pack 'proj.git'", "git-upload-pack '/proj.git'", "git-upload-pack 'proj'",
                    "git-upload-pack 'tester/proj.git'", "git upload-pack 'proj.git'"):
            r = self.ssh(cmd)
            self.assertIn("refs/heads/main", r.stdout, cmd)  # the ref advertisement (git then hangs up: no stdin)

    def test_wrong_owner_refused(self):
        self.make_repo("proj")
        User.objects.create_user("mallory", password="mallory-password")
        r = self.run_git("clone", self.ssh_url("proj", owner="mallory"), os.path.join(self.git_root, "x"), ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Repository not found", r.stderr)
        r = self.ssh("git-upload-pack 'mallory/proj.git'")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Repository not found", r.stderr)

    def test_protected_branch_refused_over_ssh(self):
        self.make_repo("prot")
        work = self.workdir()
        self.run_git("push", "-q", self.ssh_url("prot"), "main", cwd=work)
        self.c.patch("/api/git/repos/prot", {"protected": [{"pattern": "main"}]}, format="json")
        self.commit(work, {"x": "2"})
        self.run_git("push", "-q", self.ssh_url("prot"), "main", cwd=work)  # fast-forward is fine
        self.run_git("reset", "-q", "--hard", "HEAD~1", cwd=work)
        self.commit(work, {"y": "rewritten"})
        r = self.run_git("push", "-f", self.ssh_url("prot"), "main", cwd=work, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("protected", r.stderr.lower())
        r = self.run_git("push", self.ssh_url("prot"), ":main", cwd=work, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.events), 2)

    def test_unknown_key_refused(self):
        self.make_repo("proj")
        stranger, _ = keygen(self.keys, "stranger")
        r = self.ssh("git-upload-pack 'proj.git'", key=stranger)
        self.assertEqual(r.returncode, 255)
        self.assertIn("Permission denied", r.stderr)
        # No passwords or keyboard-interactive either.
        r = self.ssh("git-upload-pack 'proj.git'", key=stranger,
                     extra=["-o", "PreferredAuthentications=password,keyboard-interactive,none"])
        self.assertEqual(r.returncode, 255)
        self.assertIn("Permission denied", r.stderr)
        r = self.run_git("clone", self.ssh_url("proj"), os.path.join(self.git_root, "x"), ok=False)
        self.assertEqual(r.returncode, 0)  # (our own key still works)

    def test_removed_key_and_switched_off(self):
        self.make_repo("proj")
        self.assertTrue(self.reaches_git("git-upload-pack 'proj.git'"))
        site.update({"allow_git": False})
        r = self.ssh("git-upload-pack 'proj.git'")
        self.assertEqual(r.returncode, 255)
        site.update({"allow_git": True})
        self.assertTrue(self.reaches_git("git-upload-pack 'proj.git'"))
        u = User.objects.get(username="tester")
        u.is_active = False
        u.save()
        self.assertEqual(self.ssh("git-upload-pack 'proj.git'").returncode, 255)
        u.is_active = True
        u.save()
        SSHKey.objects.all().delete()
        self.assertEqual(self.ssh("git-upload-pack 'proj.git'").returncode, 255)

    def test_read_only_deploy_key(self):
        self.make_repo("proj")
        work = self.workdir()
        self.run_git("push", "-q", self.ssh_url("proj"), "main", cwd=work)
        dkey = self.add_key("ci", "proj", True)
        env_cmd = shlex.join(self.ssh_args(dkey))
        self.ssh_key = dkey
        dest = os.path.join(self.git_root, "dclone")
        self.run_git("clone", "-q", self.ssh_url("proj"), dest)
        self.assertTrue(os.path.exists(os.path.join(dest, "README.md")))
        self.commit(dest, {"z": "z"})
        before = len(self.events)
        r = self.run_git("push", cwd=dest, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("read-only", r.stderr)
        self.assertEqual(len(self.events), before)
        self.assertTrue(env_cmd)

    def test_read_write_deploy_key_and_isolation(self):
        self.make_repo("one")
        self.make_repo("two")
        work = self.workdir()
        self.run_git("push", "-q", self.ssh_url("two"), "main", cwd=work)
        dkey = self.add_key("deployer", "one", False)
        self.ssh_key = dkey
        self.run_git("push", "-q", self.ssh_url("one"), "main", cwd=work)
        self.assertEqual(self.events[-1].pusher, "key:deployer")
        # ...but it cannot touch the other repository, by any spelling.
        for url in (self.ssh_url("two"), self.ssh_url("two", owner="tester")):
            r = self.run_git("clone", url, os.path.join(self.git_root, "no"), ok=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Repository not found", r.stderr)
            r = self.run_git("push", url, "main", cwd=work, ok=False)
            self.assertNotEqual(r.returncode, 0)
        # Removing the deploy key (or its repository) cuts it off.
        SSHKey.objects.filter(title="deployer").delete()
        self.assertEqual(self.ssh("git-upload-pack 'one.git'").returncode, 255)

    def test_no_shell_or_other_services(self):
        r = self.ssh()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Hi tester! Kern does not provide shell access.", r.stdout + r.stderr)
        r = self.ssh(extra=["-tt"])
        self.assertIn("Kern does not provide shell access", r.stdout + r.stderr)
        for cmd in ("ls", "echo hi; id", "scp -t /tmp", "git-upload-archive 'x.git'", "git-lfs-authenticate x download",
                    "git-upload-pack", "git-upload-pack 'a.git' 'b.git'", "git-upload-pack --stateless-rpc 'a.git'",
                    "git-upload-pack 'unterminated"):
            r = self.ssh(cmd)
            self.assertEqual(r.returncode, 1, cmd)
            self.assertNotIn("uid=", r.stdout, cmd)
            self.assertTrue(r.stderr.startswith("Kern:"), (cmd, r.stderr))
        r = self.ssh(extra=["-s", "sftp"])
        self.assertNotEqual(r.returncode, 0)
        # Port forwarding is refused.
        r = subprocess.run([*self.ssh_args(), "-N", "-o", "ExitOnForwardFailure=yes", "-L", "0:127.0.0.1:22",
                            "-o", "ConnectTimeout=5", "git@127.0.0.1", "git-upload-pack 'x'"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        self.assertNotEqual(r.returncode, 0)

    def test_bad_paths_refused(self):
        self.make_repo("proj")
        marker = os.path.join(self.git_root, "pwned")
        for arg in ("../x", "../../etc/passwd", "-x", "--upload-pack=touch " + marker, "--help", "/etc/passwd",
                    "proj/../proj", "tester/../proj", "tester/proj/extra", "nope", "proj.git.git", ".git", "", "a b",
                    "//proj.git", "~/proj", "tester//proj", "proj\\x"):
            for service in ("git-upload-pack", "git-receive-pack"):
                r = self.ssh(f"{service} {shlex.quote(arg)}")
                self.assertEqual(r.returncode, 1, (service, arg, r.stderr))
                self.assertTrue(r.stderr.startswith("Kern:"), (arg, r.stderr))
        self.assertFalse(os.path.exists(marker))
        # An unquoted option is more than one argument and is refused too.
        r = self.ssh(f"git-upload-pack --upload-pack=touch {marker} proj.git")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(marker))

    def test_only_git_protocol_variable_is_forwarded(self):
        self.make_repo("proj")
        work = self.workdir()
        self.run_git("push", "-q", self.ssh_url("proj"), "main", cwd=work)
        # Protocol v2 works (git sends GIT_PROTOCOL=version=2 by default).
        r = subprocess.run(["git", "-c", "protocol.version=2", "ls-remote", self.ssh_url("proj")],
                           env=self.git_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refs/heads/main", r.stdout)
        self.assertEqual(gitssh.parse_command("git-upload-pack 'a.git'"), ("git-upload-pack", "a.git"))
        self.assertEqual(gitssh.parse_repo("/tester/a.git", "tester"), "a")
        self.assertRaises(gitssh.Refuse, gitssh.parse_repo, "other/a.git", "tester")
