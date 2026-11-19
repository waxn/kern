"""Push mirrors and webhooks. Nothing here touches the internet: mirrors push to a second repository on
the live test server, webhooks go to a small HTTP server on 127.0.0.1 (which needs the
allow_local_git_remotes site setting, the same one real private-network targets need)."""
import base64
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from accounts import site
from notes import gitmirrors, gitwebhooks, remote_guard
from notes.models_git_hooks import GitMirror, GitWebhook, GitWebhookDelivery
from notes.test_git_hosting import GitLive
from notes.tests import TEST_PASSWORD


class Receiver:
    """A local HTTP server that records requests and answers from a queue of statuses."""

    def __init__(self, statuses=None, headers=None):
        self.requests = []
        self.statuses = list(statuses or [])
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status = outer.statuses.pop(0) if outer.statuses else 200
                self.send_response(status)
                if status in (301, 302):
                    self.send_header("Location", "/elsewhere")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"answer %d" % status)

            do_GET = do_POST

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class MirrorTests(GitLive):
    def setUp(self):
        super().setUp()
        site.update({"allow_local_git_remotes": True})
        self.make_repo("src")
        self.make_repo("dst")
        self.dst_url = f"{self.live_server_url}/git/dst.git"

    def add_mirror(self, **kw):
        body = {"url": self.dst_url, "username": "tester", "secret": TEST_PASSWORD} | kw
        r = self.c.post("/api/git/repos/src/mirrors", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def dst_refs(self):
        d = self.c.get("/api/git/repos/dst").json()
        return {b["name"] for b in d["branch_list"]}, {t["name"] for t in d["tag_list"]}

    def test_push_is_mirrored_with_tags_and_pruning(self):
        m = self.add_mirror()
        self.assertTrue(m["has_secret"])
        self.assertNotIn(TEST_PASSWORD, json.dumps(m))
        work = self.workdir()
        self.run_git("tag", "v1", cwd=work)
        self.run_git("push", "-q", self.url("src"), "main", "main:feature", "--tags", cwd=work)
        self.assertEqual(self.dst_refs(), ({"main", "feature"}, {"v1"}))
        got = self.c.get("/api/git/repos/src/mirrors").json()["mirrors"][0]
        self.assertIsNotNone(got["last_success"])
        self.assertEqual(got["last_error"], "")
        # A deleted branch and tag disappear from the mirror too.
        self.run_git("push", "-q", self.url("src"), ":feature", ":refs/tags/v1", cwd=work)
        self.assertEqual(self.dst_refs(), ({"main"}, set()))
        # And a rewritten branch is force-updated.
        self.commit(work, {"x.txt": "1\n"})
        self.run_git("push", "-q", self.url("src"), "main", cwd=work)
        src = self.c.get("/api/git/repos/src").json()["branch_list"][0]["sha"]
        self.assertEqual(self.c.get("/api/git/repos/dst").json()["branch_list"][0]["sha"], src)

    def test_empty_repository_never_empties_the_remote(self):
        work = self.workdir()
        self.run_git("push", "-q", self.url("dst"), "main", cwd=work)
        self.add_mirror()  # src has nothing: syncing must not prune dst
        self.assertEqual(self.dst_refs()[0], {"main"})

    def test_credentials_stay_out_of_argv_url_and_stored_errors(self):
        m = self.add_mirror(secret="s3cret-token-xyz")
        seen = []
        real = gitmirrors._run

        def spy(cmd, env, timeout):
            seen.append((list(cmd), dict(env)))
            return real(cmd, env, timeout)

        work = self.workdir()
        with mock.patch.object(gitmirrors, "_run", spy):
            self.run_git("push", "-q", self.url("src"), "main", cwd=work)
        self.assertEqual(len(seen), 1)
        cmd, env = seen[0]
        b64 = base64.b64encode(b"tester:s3cret-token-xyz").decode()
        self.assertNotIn("s3cret-token-xyz", " ".join(cmd))
        self.assertNotIn(b64, " ".join(cmd))
        self.assertIn("--prune", cmd)
        self.assertTrue(any(b64 in v for v in env.values()))  # it travels in the environment instead
        # The wrong token is refused by the remote; the stored error mentions neither token nor header.
        row = GitMirror.objects.get(id=m["id"])
        self.assertNotEqual(row.last_error, "")
        for leak in ("s3cret-token-xyz", b64):
            self.assertNotIn(leak, row.last_error)
        self.assertNotIn("s3cret-token-xyz", row.secret_enc)  # encrypted at rest
        r = self.c.get("/api/git/repos/src/mirrors")
        self.assertNotIn("s3cret-token-xyz", r.content.decode())

    def test_scrub_removes_secrets_and_url_credentials(self):
        out = gitmirrors.scrub("fatal: https://bob:pw@example.com/x failed; Authorization: Basic QUJD tok123", ["tok123"])
        self.assertNotIn("bob", out)
        self.assertNotIn("pw@", out)
        self.assertNotIn("QUJD", out)
        self.assertNotIn("tok123", out)

    def test_url_rules(self):
        for bad in ("https://u:p@8.8.8.8/x.git", "http://8.8.8.8/x.git", "ftp://8.8.8.8/x", "8.8.8.8/x", "https://"):
            r = self.c.post("/api/git/repos/src/mirrors", {"url": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(GitMirror.objects.count(), 0)

    def test_private_addresses_need_the_site_setting(self):
        site.update({"allow_local_git_remotes": False})
        r = self.c.post("/api/git/repos/src/mirrors", {"url": self.dst_url}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("private network", r.json()["error"] if "error" in r.json() else str(r.json()))
        self.assertEqual(GitMirror.objects.count(), 0)
        site.update({"allow_local_git_remotes": True})
        m = self.add_mirror()
        # Turned off again later: the stored mirror refuses to connect when it next runs.
        site.update({"allow_local_git_remotes": False})
        work = self.workdir()
        self.run_git("push", "-q", self.url("src"), "main", cwd=work)
        self.assertEqual(self.dst_refs()[0], set())
        row = GitMirror.objects.get(id=m["id"])
        self.assertIn("private network", row.last_error)
        for ip in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1", "192.168.0.9"):
            host = f"[{ip}]" if ":" in ip else ip
            with self.assertRaises(remote_guard.RemoteNotAllowed, msg=ip):
                remote_guard.check_url(f"https://{host}/x.git")

    def test_branch_filters(self):
        work = self.workdir()
        self.run_git("push", "-q", self.url("src"), "main", "main:release/1", "main:wip", cwd=work)
        self.c.patch("/api/git/repos/src", {"protected": [{"pattern": "main"}]}, format="json")
        m = self.add_mirror(only_protected=True)
        self.assertEqual(self.dst_refs()[0], {"main"})
        r = self.c.patch(f"/api/git/repos/src/mirrors/{m['id']}", {"only_protected": False, "branch_filter": "release/* wip"},
                         format="json")
        self.assertEqual(r.json()["branch_filter"], "release/* wip")
        self.c.post(f"/api/git/repos/src/mirrors/{m['id']}/sync")
        self.assertEqual(self.dst_refs()[0], {"main", "release/1", "wip"})  # main stays; filters only choose what is pushed

    def test_sync_now_and_disable(self):
        work = self.workdir()
        self.run_git("push", "-q", self.url("src"), "main", "main:side", cwd=work)
        m = self.add_mirror()
        self.assertEqual(self.dst_refs()[0], {"main", "side"})
        self.run_git("push", "-q", self.url("dst"), ":side", cwd=work)
        self.assertEqual(self.dst_refs()[0], {"main"})
        r = self.c.patch(f"/api/git/repos/src/mirrors/{m['id']}", {"enabled": False}, format="json")
        self.assertFalse(r.json()["enabled"])
        self.assertEqual(self.c.post(f"/api/git/repos/src/mirrors/{m['id']}/sync").status_code, 400)
        self.c.patch(f"/api/git/repos/src/mirrors/{m['id']}", {"enabled": True}, format="json")
        self.assertEqual(self.c.post(f"/api/git/repos/src/mirrors/{m['id']}/sync").status_code, 202)
        self.assertEqual(self.dst_refs()[0], {"main", "side"})

    def test_requests_coalesce_into_one_more_run(self):
        m = self.add_mirror()
        gate, entered, calls = threading.Event(), threading.Event(), []

        def slow(mirror):
            calls.append(1)
            entered.set()
            gate.wait(10)
            return None

        with mock.patch.object(gitmirrors, "push_once", slow):
            first = threading.Thread(target=gitmirrors.request_sync, args=(m["id"], True))
            first.start()
            self.assertTrue(entered.wait(10))
            self.assertTrue(gitmirrors.is_syncing(m["id"]))
            for _ in range(5):  # while running: only marked dirty
                self.assertEqual(gitmirrors.request_sync(m["id"], block=True), "queued")
            gate.set()
            first.join(10)
        self.assertEqual(len(calls), 2)  # the running one plus exactly one more
        self.assertFalse(gitmirrors.is_syncing(m["id"]))

    def test_repository_deletion_removes_mirrors_and_hooks(self):
        self.add_mirror()
        h = self.c.post("/api/git/repos/src/webhooks", {"url": "http://127.0.0.1:9/x", "events": ["push"]}, format="json")
        self.assertEqual(h.status_code, 201, h.content)
        GitWebhookDelivery.objects.create(hook_id=h.json()["id"], event="ping")
        self.assertEqual(self.c.delete("/api/git/repos/src").status_code, 204)
        self.assertEqual(GitMirror.objects.count(), 0)
        self.assertEqual(GitWebhook.objects.count(), 0)
        self.assertEqual(GitWebhookDelivery.objects.count(), 0)


class WebhookTests(GitLive):
    def setUp(self):
        super().setUp()
        site.update({"allow_local_git_remotes": True})
        self.make_repo("wh")
        self._backoff = mock.patch.object(gitwebhooks, "BACKOFF", (0, 0))
        self._backoff.start()
        self.addCleanup(self._backoff.stop)

    def receiver(self, **kw):
        r = Receiver(**kw)
        self.addCleanup(r.close)
        return r

    def add_hook(self, rcv, **kw):
        body = {"url": rcv.url, "secret": "topsecret", "events": ["push"]} | kw
        r = self.c.post("/api/git/repos/wh/webhooks", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_push_delivery_is_signed_and_describes_the_push(self):
        rcv = self.receiver()
        hook = self.add_hook(rcv)
        self.assertTrue(hook["has_secret"])
        self.assertNotIn("topsecret", json.dumps(hook))
        work = self.workdir(msg="Initial commit")
        sha1 = self.run_git("rev-parse", "HEAD", cwd=work).stdout.strip()
        self.run_git("push", "-q", self.url("wh"), "main", cwd=work)
        sha2 = self.commit(work, {"a.txt": "1\n"}, "Second")
        self.run_git("push", "-q", self.url("wh"), "main", cwd=work)
        self.assertEqual(len(rcv.requests), 2)  # one delivery per push
        req = rcv.requests[1]
        h = req["headers"]
        self.assertEqual(h["Content-Type"], "application/json")
        self.assertEqual(h["User-Agent"], "Kern-Hookshot")
        self.assertEqual(h["X-Kern-Event"], "push")
        self.assertTrue(h["X-Kern-Delivery"])
        expect = "sha256=" + hmac.new(b"topsecret", req["body"], hashlib.sha256).hexdigest()
        self.assertEqual(h["X-Kern-Signature-256"], expect)
        data = json.loads(req["body"])
        self.assertEqual(data["event"], "push")
        self.assertEqual(data["repository"], {"name": "wh", "owner": "tester"})
        self.assertEqual((data["pusher"], data["via"]), ("tester", "http"))
        self.assertTrue(data["timestamp"])
        (ref,) = data["refs"]
        self.assertEqual((ref["ref"], ref["before"], ref["after"]), ("refs/heads/main", sha1, sha2))
        self.assertEqual((ref["created"], ref["deleted"]), (False, False))
        self.assertEqual([c["sha"] for c in ref["commits"]], [sha2])
        self.assertEqual(ref["commits"][0]["subject"], "Second")
        self.assertEqual(ref["commits"][0]["author"], "Ada")
        first = json.loads(rcv.requests[0]["body"])["refs"][0]
        self.assertTrue(first["created"])
        self.assertEqual(first["commits"][0]["subject"], "Initial commit")
        # The delivery log has it all.
        d = self.c.get(f"/api/git/repos/wh/webhooks/{hook['id']}/deliveries").json()["deliveries"]
        self.assertEqual(len(d), 2)
        self.assertEqual((d[0]["status_code"], d[0]["ok"], d[0]["event"]), (200, True, "push"))
        full = self.c.get(f"/api/git/repos/wh/webhooks/{hook['id']}/deliveries/{d[0]['id']}").json()
        self.assertEqual(json.loads(full["request_body"])["event"], "push")
        self.assertEqual(full["response_body"], "answer 200")

    def test_only_subscribed_events_and_enabled_hooks(self):
        rcv = self.receiver()
        h = self.add_hook(rcv)
        self.assertEqual(gitwebhooks.emit(self.user_id(), "wh", "release", {"tag": "v1"}), 0)
        gitwebhooks.register_event("release", "Release published")
        self.addCleanup(gitwebhooks.EVENTS.pop, "release", None)
        self.assertEqual(gitwebhooks.emit(self.user_id(), "wh", "release", {"tag": "v1"}), 0)  # not subscribed
        r = self.c.patch(f"/api/git/repos/wh/webhooks/{h['id']}", {"events": ["push", "release"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(gitwebhooks.emit(self.user_id(), "wh", "release", {"tag": "v1"}), 1)
        self.assertEqual(json.loads(rcv.requests[0]["body"])["tag"], "v1")
        self.c.patch(f"/api/git/repos/wh/webhooks/{h['id']}", {"enabled": False}, format="json")
        self.assertEqual(gitwebhooks.emit(self.user_id(), "wh", "release", {"tag": "v2"}), 0)
        bad = self.c.patch(f"/api/git/repos/wh/webhooks/{h['id']}", {"events": ["nonsense"]}, format="json")
        self.assertEqual(bad.status_code, 400)

    def user_id(self):
        from django.contrib.auth.models import User
        return User.objects.get(username="tester").id

    def test_retries_on_5xx_then_succeeds(self):
        rcv = self.receiver(statuses=[500, 503, 200])
        hook = self.add_hook(rcv)
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(rcv.requests), 3)
        self.assertEqual((r.json()["ok"], r.json()["attempts"], r.json()["status_code"]), (True, 3, 200))

    def test_gives_up_after_two_retries(self):
        rcv = self.receiver(statuses=[500, 500, 500, 500])
        hook = self.add_hook(rcv)
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test").json()
        self.assertEqual(len(rcv.requests), 3)
        self.assertEqual((r["ok"], r["attempts"], r["status_code"]), (False, 3, 500))
        self.assertIn("500", r["error"])

    def test_4xx_is_not_retried_and_network_errors_are(self):
        rcv = self.receiver(statuses=[404])
        hook = self.add_hook(rcv)
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test").json()
        self.assertEqual((len(rcv.requests), r["ok"], r["attempts"]), (1, False, 1))
        rcv.close()  # nobody is listening any more
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test").json()
        self.assertEqual((r["ok"], r["attempts"], r["status_code"]), (False, 3, None))
        self.assertTrue(r["error"])

    def test_redirects_are_not_followed(self):
        rcv = self.receiver(statuses=[302, 200])
        hook = self.add_hook(rcv)
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test").json()
        self.assertEqual(len(rcv.requests), 1)
        self.assertEqual((r["ok"], r["status_code"]), (False, 302))

    def test_ping_and_redeliver(self):
        rcv = self.receiver()
        hook = self.add_hook(rcv, events=["push"])
        r = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test")
        ping = r.json()
        self.assertEqual(rcv.requests[0]["headers"]["X-Kern-Event"], "ping")
        self.assertEqual(json.loads(rcv.requests[0]["body"])["event"], "ping")
        again = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/deliveries/{ping['id']}/redeliver").json()
        self.assertEqual(len(rcv.requests), 2)
        self.assertEqual(rcv.requests[1]["body"], rcv.requests[0]["body"])
        self.assertNotEqual(again["guid"], ping["guid"])
        self.assertEqual(rcv.requests[1]["headers"]["X-Kern-Delivery"], again["guid"])
        self.assertTrue(rcv.requests[1]["headers"]["X-Kern-Signature-256"].startswith("sha256="))

    def test_no_secret_means_no_signature_and_log_is_trimmed(self):
        rcv = self.receiver()
        hook = self.add_hook(rcv, secret="")
        self.assertFalse(hook["has_secret"])
        with mock.patch.object(gitwebhooks, "KEEP_DELIVERIES", 3):
            for _ in range(5):
                self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test")
        self.assertNotIn("X-Kern-Signature-256", rcv.requests[0]["headers"])
        self.assertEqual(GitWebhookDelivery.objects.filter(hook_id=hook["id"]).count(), 3)

    def test_private_targets_need_the_site_setting(self):
        rcv = self.receiver()
        hook = self.add_hook(rcv)
        site.update({"allow_local_git_remotes": False})
        r = self.c.post("/api/git/repos/wh/webhooks", {"url": rcv.url, "events": ["push"]}, format="json")
        self.assertEqual(r.status_code, 400)
        d = self.c.post(f"/api/git/repos/wh/webhooks/{hook['id']}/test").json()  # an existing hook is refused too
        self.assertFalse(d["ok"])
        self.assertEqual(rcv.requests, [])
        self.assertIn("private network", d["error"])
        bad = self.c.post("/api/git/repos/wh/webhooks", {"url": "https://u:p@8.8.8.8/", "events": ["push"]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.c.post("/api/git/repos/wh/webhooks", {"url": "gopher://8.8.8.8/", "events": ["push"]},
                                     format="json").status_code, 400)
