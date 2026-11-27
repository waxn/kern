"""Apps: names and routes, the build plan, the gateway's rules, the API, and a real deployment of a
template run by the supervisor and served through the gateway."""
import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import types
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from notes.tests import TEST_PASSWORD, authed

from . import api, builder, core, dbexplore, deploy, gateway, isolation, source, tasks
from .models import App, BuilderChat, Deployment

REPO = Path(__file__).resolve().parents[2]


class RoutesTests(SimpleTestCase):
    """An app may never take a path the Kern web app uses."""

    def test_reserved_covers_every_frontend_route(self):
        routes = REPO / "frontend" / "src" / "routes"
        if not routes.is_dir():
            self.skipTest("frontend not checked out")
        top = {p.name for p in routes.iterdir() if p.is_dir() and not p.name.startswith(("(", "["))}
        self.assertEqual(top - core.KERN_ROUTES, set(), "add these to core.KERN_ROUTES and kernRoutes.ts")
        ts = (REPO / "frontend" / "src" / "lib" / "kernRoutes.ts").read_text()
        listed = set(re.findall(r"'([a-z-]+)'", ts.split("KERN_SYSTEM")[0]))
        self.assertEqual(listed, core.KERN_ROUTES)

    def test_slugs(self):
        for ok in ("chickens", "claude-usage", "a", "x1"):
            self.assertTrue(core.valid_slug(ok), ok)
        for bad in ("api", "mail", "git", "Apps", "-x", "x-", "a--b", "a_b", "a.b", "", "x" * 41, "_app", "pdfjs"):
            self.assertFalse(core.valid_slug(bad), bad)
        self.assertEqual(core.suggest_slug("Chicken Weights!"), "chicken-weights")
        self.assertEqual(core.suggest_slug("Mail"), "mail-app")

    def test_public_paths(self):
        self.assertEqual(core.clean_public_paths(["api/ingest", "/api/ingest", "/", "../x", "/hook/"]), ["/api/ingest", "/hook"])
        app = App(public_paths=["/api/ingest"])
        self.assertTrue(core.path_is_public(app, "/api/ingest"))
        self.assertTrue(core.path_is_public(app, "/api/ingest/batch"))
        self.assertFalse(core.path_is_public(app, "/api/ingestx"))
        self.assertFalse(core.path_is_public(app, "/"))


class PlanTests(SimpleTestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.app = App(runtime="", build_cmd="", start_cmd="", health_path="")

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, name, text=""):
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_static(self):
        self.write("index.html", "<h1>hi</h1>")
        p = core.make_plan(self.app, self.d)
        self.assertEqual((p.runtime, p.start, p.build), ("static", "", []))

    def test_python_with_requirements(self):
        self.write("main.py")
        self.write("requirements.txt", "flask")
        p = core.make_plan(self.app, self.d)
        self.assertEqual(p.runtime, "python")
        self.assertEqual(p.start, "python main.py")
        self.assertIn("requirements.txt", p.build[0])

    def test_node_start_script_and_deps(self):
        self.write("package.json", '{"scripts": {"start": "node x.js", "build": "vite build"}, "dependencies": {"a": "1"}}')
        self.write("package-lock.json", "{}")
        p = core.make_plan(self.app, self.d)
        self.assertEqual(p.start, "npm start")
        self.assertEqual(p.build, ["npm ci --no-audit --no-fund", "npm run build"])

    def test_node_frontend_only_is_served_static(self):
        self.write("package.json", '{"scripts": {"build": "vite build"}, "devDependencies": {"vite": "1"}}')
        p = core.make_plan(self.app, self.d)
        self.assertEqual(p.runtime, "static")
        self.write("dist/index.html", "x")
        self.assertEqual(core.static_root(self.d, p), self.d / "dist")

    def test_manifest_wins_and_settings_win_over_it(self):
        self.write("app.py")
        self.write(".kern/app.yml", "runtime: command\nstart: ./run.sh\nhealth: /up\nenv: {MODE: x, PORT: 1}\n")
        p = core.make_plan(self.app, self.d)
        self.assertEqual((p.runtime, p.start, p.health, p.env), ("command", "./run.sh", "/up", {"MODE": "x"}))
        self.app.start_cmd = "./other.sh"
        self.assertEqual(core.make_plan(self.app, self.d).start, "./other.sh")

    def test_unknown_project_explains(self):
        self.write("notes.txt")
        with self.assertRaisesRegex(core.PlanError, "could not tell"):
            core.make_plan(self.app, self.d)
        self.write(".kern/app.yml", "static: ../../etc\nruntime: static\n")
        with self.assertRaisesRegex(core.PlanError, "outside"):
            core.make_plan(self.app, self.d)

    def test_env_is_built_from_nothing(self):
        app = App(id=7, slug="x", name="X", secret="s3", env_enc="")
        with mock.patch.dict(os.environ, {"KERN_SECRET_KEY": "leak", "KERN_DATA_DIR": "/data", "AWS_SECRET": "z"}):
            env = core.app_env(app, 9300, self.d, core.Plan(runtime="python"), self.d)
        self.assertNotIn("KERN_SECRET_KEY", env)
        self.assertNotIn("KERN_DATA_DIR", env)
        self.assertNotIn("AWS_SECRET", env)
        self.assertEqual((env["PORT"], env["KERN_BASE_PATH"], env["KERN_APP_SECRET"]), ("9300", "/x", "s3"))


class IsolationTests(SimpleTestCase):
    def test_wrap_drops_everything_without_needing_setpcap(self):
        with mock.patch.object(isolation, "_isolated", True):
            cmd = isolation.wrap(["sh", "-c", "x"], 5)
        self.assertEqual(cmd[:2], ["setpriv", "--reuid=20005"])
        for flag in ("--regid=20005", "--clear-groups", "--inh-caps=-all", "--ambient-caps=-all", "--no-new-privs"):
            self.assertIn(flag, cmd)
        # Changing the bounding set needs CAP_SETPCAP, which the apps service doesn't keep.
        self.assertFalse([f for f in cmd if f.startswith("--bounding-set")])
        self.assertEqual(cmd[-4:], ["--", "sh", "-c", "x"])
        with mock.patch.object(isolation, "_isolated", False):
            self.assertEqual(isolation.wrap(["true"], 5), ["true"])


class GatewayRuleTests(SimpleTestCase):
    def setUp(self):
        self.gw = gateway.Gateway(mock.Mock())
        self.a = {"slug": "hens", "owner": 1, "access": "private", "public_paths": ["/api/ingest"], "strip_prefix": True,
                  "secret": "sek", "name": "Hens", "icon": ""}

    def test_access(self):
        me, other = {"id": 1, "username": "me"}, {"id": 2, "username": "you"}
        allowed = gateway.Gateway.allowed
        self.assertTrue(allowed(self.a, me, "/"))
        self.assertFalse(allowed(self.a, other, "/"))
        self.assertFalse(allowed(self.a, None, "/"))
        self.assertTrue(allowed(self.a, None, "/api/ingest"))
        self.assertTrue(allowed({**self.a, "access": "users"}, other, "/"))
        self.assertFalse(allowed({**self.a, "access": "users"}, None, "/"))
        self.assertTrue(allowed({**self.a, "access": "public"}, None, "/"))

    def test_location_and_cookies(self):
        rl = self.gw.rewrite_location
        self.assertEqual(rl("/login", self.a, 9200), "/hens/login")
        self.assertEqual(rl("/hens/x", self.a, 9200), "/hens/x")
        self.assertEqual(rl("http://127.0.0.1:9200/a?b=1", self.a, 9200), "/hens/a?b=1")
        self.assertEqual(rl("https://example.com/", self.a, 9200), "https://example.com/")
        self.assertEqual(rl("//evil.com", self.a, 9200), "//evil.com")
        rc = self.gw.rewrite_cookie
        self.assertIsNone(rc("kern_sid=abc; Path=/", self.a))
        self.assertEqual(rc("s=1; Path=/; HttpOnly", self.a), "s=1; Path=/hens/; HttpOnly")
        self.assertEqual(rc("s=1", self.a), "s=1; Path=/hens/")

    def test_upstream_headers_hide_kern_session(self):
        req = mock.Mock()
        req.headers = {"Cookie": "kern_sid=SECRET; theme=dark", "X-Kern-User": "forged", "Accept": "*/*", "Host": "k"}
        req.remote, req.scheme, req.host = "1.2.3.4", "http", "k"
        h = self.gw.upstream_headers(req, self.a, {"id": 1, "username": "me"})
        self.assertEqual(h["Cookie"], "theme=dark")
        self.assertEqual((h["X-Kern-User"], h["X-Kern-App-Secret"], h["X-Forwarded-Prefix"]), ("me", "sek", "/hens"))
        h = self.gw.upstream_headers(req, self.a, None)
        self.assertNotIn("X-Kern-User", h)


class AppsRoot:
    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp(prefix="kern-apps-test-")
        self.git_root = tempfile.mkdtemp(prefix="kern-git-test-")
        self._o = override_settings(KERN_APPS_DIR=self.root, KERN_GIT_ROOT=self.git_root)
        self._o.enable()
        self._kick = mock.patch.object(deploy, "kick")
        self._kick.start()
        self._iso = mock.patch.object(isolation, "_isolated", False)
        self._iso.start()

    def tearDown(self):
        self._iso.stop()
        self._kick.stop()
        self._o.disable()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.git_root, ignore_errors=True)
        super().tearDown()


class ApiTests(AppsRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.c = authed()

    def test_create_from_template_commits_and_queues(self):
        r = self.c.post("/api/apps", {"kind": "template", "template": "tracker", "name": "Hens", "slug": "hens"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        a = App.objects.get(slug="hens")
        self.assertEqual((a.source, a.repo, a.icon), ("kern", "app-hens", "📈"))
        deps = list(a.deployments.all())
        self.assertEqual(len(deps), 1)  # the push listener and the API queue the same commit once
        self.assertEqual(deps[0].status, "queued")
        files = self.c.get("/api/apps/hens/files").json()
        self.assertIn("app.py", [f["path"] for f in files["files"]])
        self.assertIn("python", self.c.get("/api/apps/hens/files?path=.kern/app.yml").json()["content"])

    def test_names_are_checked(self):
        r = self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "Mail", "slug": "mail"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "A", "slug": "taken"}, format="json")
        r = self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "B", "slug": "taken"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(self.c.get("/api/apps/check-slug?slug=taken").json()["ok"])

    def test_app_ai_config_follows_workspace_until_overridden(self):
        from notes import ai
        from notes.models import Setting

        self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "A", "slug": "a"}, format="json")
        Setting.objects.update_or_create(key="ai", defaults={"value": {"provider": "ollama", "model": "llama", "base_url": "http://x/v1"}})
        r = self.c.get("/api/apps/a/ai").json()
        self.assertTrue(r["inherited"])
        self.assertEqual((r["provider"], r["model"]), ("ollama", "llama"))
        r = self.c.put("/api/apps/a/ai", {"provider": "openai", "model": "gpt-5", "base_url": "https://api.openai.com/v1",
                                          "api_key": "sk-test-12345678"}, format="json").json()
        self.assertFalse(r["inherited"])
        self.assertEqual((r["provider"], r["model"]), ("openai", "gpt-5"))
        self.assertTrue(r["own_key"])
        # Only this app changed: the workspace keeps its provider.
        self.assertEqual(ai.config()["provider"], "ollama")
        self.assertEqual(ai.config("a")["provider"], "openai")
        # Back to the workspace settings.
        r = self.c.put("/api/apps/a/ai", {"inherit": True}, format="json").json()
        self.assertTrue(r["inherited"])
        self.assertEqual(r["provider"], "ollama")

    def test_settings_env_and_edit(self):
        self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "S", "slug": "s"}, format="json")
        r = self.c.patch("/api/apps/s", {"access": "public", "public_paths": ["api/in"], "slug": "s2"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["access"], r.json()["public_paths"], r.json()["slug"]), ("public", ["/api/in"], "s2"))
        r = self.c.put("/api/apps/s2/env", {"vars": {"TOKEN": "abc"}}, format="json")
        self.assertEqual(r.json()["vars"], [{"name": "TOKEN", "value": "abc"}])
        self.assertNotIn("abc", App.objects.get(slug="s2").env_enc)  # encrypted at rest
        self.assertEqual(self.c.put("/api/apps/s2/env", {"vars": {"PORT": "1"}}, format="json").status_code, 400)
        r = self.c.put("/api/apps/s2/files", {"path": "about.html", "content": "<p>hi</p>"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(App.objects.get(slug="s2").deployments.filter(trigger="edit").count(), 1)

    def test_other_users_and_non_admins(self):
        self.c.post("/api/apps", {"kind": "template", "template": "static", "name": "Mine", "slug": "mine"}, format="json")
        other = User.objects.create_user("other", password=TEST_PASSWORD, is_staff=False)
        from rest_framework.test import APIClient

        c2 = APIClient(HTTP_X_KERN="1")
        c2.force_login(other)
        self.assertEqual(c2.get("/api/apps").status_code, 403)  # apps are for administrators by default
        from accounts import site

        site.update({"apps_access": "everyone"})
        self.assertEqual(c2.get("/api/apps").json()["apps"], [])
        self.assertEqual(c2.get("/api/apps/mine").status_code, 404)


class DeployTests(AppsRoot, TransactionTestCase):
    """The whole path: a template app is built, started on its own port and served by the gateway."""

    def setUp(self):
        super().setUp()
        self.c = authed()
        self._ctl = mock.patch.object(core, "control_token", return_value="t")
        self._ctl.start()

    def tearDown(self):
        self._ctl.stop()
        super().tearDown()

    def test_deploy_serve_crash_and_rollback(self):
        from .supervisor import Supervisor

        r = self.c.post("/api/apps", {"kind": "template", "template": "tracker", "name": "Hens", "slug": "hens"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        app = App.objects.get(slug="hens")
        user = User.objects.get(username="tester")

        async def run():
            sup = Supervisor()
            gw = gateway.Gateway(sup)
            await gw.start()
            client = TestClient(TestServer(gw.app()))
            await client.start_server()
            try:
                await sup.sync()
                for _ in range(200):
                    await asyncio.sleep(0.1)
                    if not sup.deploy_tasks:
                        break
                rt = sup.find("hens")
                self.assertIsNotNone(rt.current, deploy.tail(core.deploy_log(app.id, 1)))
                gw.sessions.user = mock.AsyncMock(return_value={"id": user.id, "username": "tester", "admin": True})
                res = await client.get("/hens/api/entries")
                self.assertEqual(res.status, 200)
                self.assertEqual(await res.json(), [])
                res = await client.post("/hens/api/entries", json={"subject": "Hen", "value": 2.5})
                self.assertEqual(res.status, 201)
                res = await client.get("/hens", allow_redirects=False)
                self.assertEqual(res.status, 308)
                res = await client.get("/mail/inbox")
                self.assertEqual(res.headers.get("X-Kern-Noapp"), "1")
                # Signed out: browsers are sent to sign in, other clients get 401.
                gw.sessions.user = mock.AsyncMock(return_value=None)
                res = await client.get("/hens/", headers={"Accept": "text/html"}, allow_redirects=False)
                self.assertEqual((res.status, res.headers["Location"]), (302, "/login?next=/hens/"))
                self.assertEqual((await client.get("/hens/api/entries")).status, 401)

                # A second deployment that can't start leaves the first one serving.
                await asyncio.to_thread(lambda: (
                    App.objects.filter(pk=app.pk).update(start_cmd="python -c 'import sys; print(\"boot trouble: no config\", file=sys.stderr); raise SystemExit(3)'"),
                    deploy.queue(App.objects.get(pk=app.pk), "manual", "t")))
                await sup.sync()
                for _ in range(200):
                    await asyncio.sleep(0.1)
                    if not sup.deploy_tasks:
                        break
                d2 = await asyncio.to_thread(lambda: Deployment.objects.get(app=app, number=2))
                self.assertEqual(d2.status, "failed")
                self.assertIn("exited with code 3", d2.error)
                self.assertEqual(rt.current.number, 1)
                gw.sessions.user = mock.AsyncMock(return_value={"id": user.id, "username": "tester", "admin": True})
                self.assertEqual((await client.get("/hens/api/entries")).status, 200)

                # The app's data lives in APP_DATA_DIR, outside the release.
                self.assertTrue((core.data_dir(app.id) / "tracker.db").is_file())

                async def settle():
                    await sup.sync()
                    for _ in range(200):
                        await asyncio.sleep(0.1)
                        if not sup.deploy_tasks and rt.current and rt.current.alive() and not rt.starting:
                            return
                    self.fail("the app did not come up")

                # Roll back to #1 (reusing its files), then restart: it must start from #1's folder.
                await asyncio.to_thread(lambda: (
                    App.objects.filter(pk=app.pk).update(start_cmd=""),
                    deploy.queue(App.objects.get(pk=app.pk), "rollback", "t", sha=d2.sha, rollback_of=1)))
                await settle()
                d3 = await asyncio.to_thread(lambda: Deployment.objects.get(app=app, number=3))
                self.assertEqual(d3.status, "live", d3.error)
                self.assertEqual(rt.app["release"], 1)
                await sup.restart(app.id)
                await settle()
                self.assertEqual((await client.get("/hens/api/entries")).status, 200)
                self.assertEqual(len(await (await client.get("/hens/api/entries")).json()), 1)

                # A crash is restarted by itself.
                pid = rt.current.pid
                os.killpg(pid, 9)
                for _ in range(100):
                    await asyncio.sleep(0.1)
                    if rt.current is None:
                        break
                await asyncio.sleep(1.2)  # first backoff is 1 s
                await settle()
                self.assertNotEqual(rt.current.pid, pid)
                self.assertEqual(rt.restarts, 1)
                self.assertEqual((await client.get("/hens/api/entries")).status, 200)
            finally:
                await sup.shutdown()
                await client.close()
                await gw.close()

        asyncio.run(run())
        self.check_logs(app)

    def check_logs(self, app):
        """Every phase of the three deployments left a timestamped line, and the failed one says why."""
        stamp = r"\[\d\d:\d\d:\d\d\]"
        r1 = self.c.get("/api/apps/hens/deploys/1/log").json()
        self.assertTrue(r1["done"])
        for header in ("Get the code", "Write the release", "Plan", "Start on port", "Wait for the app to answer",
                       "Switch traffic"):
            self.assertRegex(r1["text"], rf"(?m)^{stamp} ▸ {header}", header)
        self.assertRegex(r1["text"], rf"(?m)^{stamp} ✓ Live .*in total")
        self.assertEqual(r1["phases"][0]["name"], "Get the code")
        self.assertEqual({p["status"] for p in r1["phases"]}, {"ok"})
        self.assertTrue(all(p["seconds"] is not None and p["started"] for p in r1["phases"]))

        r2 = self.c.get("/api/apps/hens/deploys/2/log").json()
        self.assertEqual((r2["status"], r2["done"]), ("failed", True))
        self.assertIn("boot trouble: no config", r2["text"])  # the app's stderr, from its startup
        self.assertIn("exited with code 3", r2["text"])
        self.assertRegex(r2["text"], rf"(?m)^{stamp} ✗ Deployment failed: .*exited with code 3")
        self.assertRegex(r2["text"], r"(?m)^  ! boot trouble")  # marked as stderr
        self.assertEqual([p["status"] for p in r2["phases"]][-1], "fail")
        self.assertEqual(r2["phases"][-1]["name"], "Wait for the app to answer")
        # The end of the file is the last thing written: nothing after the final line.
        self.assertRegex(r2["text"].rstrip().splitlines()[-1], rf"^{stamp} ✗ Deployment failed")

        r3 = self.c.get("/api/apps/hens/deploys/3/log").json()
        self.assertRegex(r3["text"], rf"(?m)^{stamp} ▸ Roll back to deployment #1")
        self.assertRegex(r3["text"], rf"(?m)^{stamp} ▸ Stop the old version #1")
        # "Live" is the last line: the old process is stopped (and logged) before the deployment is over.
        self.assertRegex(r3["text"].rstrip().splitlines()[-1], rf"^{stamp} ✓ Live")
        names = [p["name"] for p in r3["phases"]]
        self.assertLess(names.index("Switch traffic"), names.index("Stop the old version #1"))


# ------------------------------------------------------------------------------------ deploy log


class DeployLogTests(AppsRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.c = authed()
        self.user = User.objects.get(username="tester")
        self.app = App.objects.create(owner=self.user.id, slug="hens", name="Hens", secret="s", hook_secret="h")

    def test_build_steps_leave_exit_code_and_duration(self):
        lg = deploy.Log(core.deploy_log(self.app.id, 1))
        env = {"PATH": os.environ["PATH"]}
        deploy._run_step(self.app, "echo building; echo oops >&2", Path(self.root), env, lg, lambda: False)
        with self.assertRaises(deploy.DeployError) as cm:
            deploy._run_step(self.app, "echo before; exit 3", Path(self.root), env, lg, lambda: False, " 2/2")
        self.assertIn("exit code 3", str(cm.exception))
        lg.close()
        text = core.deploy_log(self.app.id, 1).read_text()
        self.assertIn("oops", text)  # stderr is in the log
        self.assertRegex(text, r"(?m)^\[\d\d:\d\d:\d\d\] ▸ Build: echo building; echo oops >&2")
        self.assertRegex(text, r"(?m)^\[\d\d:\d\d:\d\d\] ✓ exit 0 · [\d.]+ s")
        self.assertRegex(text, r"(?m)^\[\d\d:\d\d:\d\d\] ✗ exit 3 · [\d.]+ s")
        ph = deploy.read_phases(self.app.id, 1)
        self.assertEqual([(p["status"]) for p in ph], ["ok", "fail"])
        self.assertTrue(ph[1]["name"].startswith("Build 2/2: "))

    def test_phases_survive_a_second_log_and_a_dead_worker(self):
        a = deploy.Log(core.deploy_log(self.app.id, 4))
        a.phase("One")
        a.end(True, "fine")
        a.phase("Two")
        a.close()
        b = deploy.Log(core.deploy_log(self.app.id, 4))  # picks up where the first stopped
        self.assertEqual(b.running["name"], "Two")
        b.phase("Three")
        b.close()
        self.assertEqual([(p["name"], p["status"]) for p in deploy.read_phases(self.app.id, 4)],
                         [("One", "ok"), ("Two", "ok"), ("Three", "running")])
        self.assertEqual(deploy.read_phases(self.app.id, 4, finished=True)[-1]["status"], "fail")
        self.assertEqual(deploy.read_phases(self.app.id, 99), [])  # an old deployment: no phases, no error

    def test_done_waits_for_the_worker_to_finish_writing(self):
        d = Deployment.objects.create(app=self.app, number=1, status="building")
        core.deploy_log(self.app.id, 1).parent.mkdir(parents=True, exist_ok=True)
        core.deploy_log(self.app.id, 1).write_text("[10:00:00] ▸ Build\n")
        url = "/api/apps/hens/deploys/1/log"
        r = self.c.get(url).json()
        self.assertFalse(r["done"])
        # Cancelled from the UI while building: the status says so, but the worker is still writing.
        Deployment.objects.filter(pk=d.pk).update(status="cancelled")
        r = self.c.get(url).json()
        self.assertEqual((r["status"], r["done"]), ("cancelled", False))
        with open(core.deploy_log(self.app.id, 1), "a") as f:
            f.write("[10:00:01] ✗ Cancelled\n")
        Deployment.objects.filter(pk=d.pk).update(finished=deploy.timezone.now())
        r = self.c.get(url + "?offset=" + str(r["offset"])).json()
        self.assertEqual((r["text"], r["done"]), ("[10:00:01] ✗ Cancelled\n", True))
        self.assertEqual(r["phases"], [])

    def test_a_long_log_is_not_cut_and_not_done_until_read(self):
        Deployment.objects.create(app=self.app, number=1, status="live", finished=deploy.timezone.now())
        line = "x" * 99 + "\n"
        core.deploy_log(self.app.id, 1).parent.mkdir(parents=True, exist_ok=True)
        core.deploy_log(self.app.id, 1).write_text(line * 6000)  # 600 KB: more than one chunk
        got, off, done = "", 0, False
        for _ in range(10):
            r = self.c.get(f"/api/apps/hens/deploys/1/log?offset={off}").json()
            got, off, done = got + r["text"], r["offset"], r["done"]
            if done:
                break
            self.assertFalse(done)
        self.assertEqual(got, line * 6000)
        self.assertTrue(done)

    def test_recover_ends_the_log_of_a_cut_off_deployment(self):
        Deployment.objects.create(app=self.app, number=1, status="starting", started=deploy.timezone.now())
        lg = deploy.Log(core.deploy_log(self.app.id, 1))
        lg.phase("Wait for the app to answer")
        lg.close()
        deploy.recover()
        self.assertEqual(Deployment.objects.get(app=self.app, number=1).status, "failed")
        self.assertRegex(core.deploy_log(self.app.id, 1).read_text(), r"(?m)^\[.*\] ✗ The apps service restarted")
        self.assertEqual(deploy.read_phases(self.app.id, 1, finished=True)[0]["status"], "fail")


# ------------------------------------------------------------------------- database explorer


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class DbExploreTests(AppsRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.c = authed()
        self.user = User.objects.get(username="tester")
        self.app = App.objects.create(owner=self.user.id, slug="hens", name="Hens", secret="s", hook_secret="h")
        self.data = core.data_dir(self.app.id)
        self.data.mkdir(parents=True)
        self.outside = Path(tempfile.mkdtemp(prefix="kern-outside-"))  # stands for Kern's own files
        self.secret_db = self.outside / "kern.sqlite3"
        con = sqlite3.connect(self.secret_db)
        con.execute("CREATE TABLE secrets (v TEXT)")
        con.execute("INSERT INTO secrets VALUES ('the-key-to-everything')")
        con.commit()
        con.close()
        self.db = self.data / "app.db"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, weight REAL, pic BLOB, note TEXT);
            CREATE VIEW heavy AS SELECT name FROM items WHERE weight > 2;
        """)
        con.executemany("INSERT INTO items (name, weight, pic, note) VALUES (?,?,?,?)",
                        [(f"hen {i}", i / 2, b"\x00" * 1000, "n" * 5000 if i == 3 else "short") for i in range(1, 8)])
        con.commit()
        con.close()
        self.before = sha(self.db)

    def tearDown(self):
        shutil.rmtree(self.outside, ignore_errors=True)
        super().tearDown()

    def get(self, path):
        return self.c.get("/api/apps/hens/" + path)

    def query(self, sql, file="app.db"):
        return self.c.post("/api/apps/hens/db/query", {"file": file, "sql": sql}, format="json")

    # -- structure
    def test_files_and_tables(self):
        (self.data / "sub").mkdir()
        shutil.copy(self.db, self.data / "sub" / "other.db")
        (self.data / "notes.db").write_text("not a database")
        (self.data / "deep" / "a" / "b" / "c" / "d").mkdir(parents=True)
        shutil.copy(self.db, self.data / "deep" / "a" / "b" / "c" / "d" / "too-deep.db")
        r = self.get("db").json()
        self.assertEqual({f["path"]: f["is_sqlite"] for f in r["files"]},
                         {"app.db": True, "sub/other.db": True, "notes.db": False})
        self.assertIsNone(r["file"])  # two databases: the caller chooses
        self.assertEqual(r["tables"], [])
        (self.data / "sub" / "other.db").unlink()
        r = self.get("db").json()  # exactly one SQLite file: selected
        self.assertEqual(r["file"], "app.db")
        t = {x["name"]: x for x in r["tables"]}
        self.assertEqual((t["items"]["kind"], t["items"]["rows"]), ("table", 7))
        self.assertEqual((t["heavy"]["kind"], t["heavy"]["rows"]), ("view", 3))
        self.assertEqual(t["items"]["columns"][0], {"name": "id", "type": "INTEGER", "pk": True})
        self.assertEqual([c["name"] for c in t["items"]["columns"]], ["id", "name", "weight", "pic", "note"])
        self.assertNotIn("sqlite_sequence", t)
        self.assertEqual(self.get("db?file=app.db").json()["file"], "app.db")
        self.assertEqual(sha(self.db), self.before)

    def test_a_table_that_cannot_be_counted_still_lists(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE VIEW broken AS SELECT * FROM gone")
        con.commit()
        con.close()
        t = {x["name"]: x for x in self.get("db?file=app.db").json()["tables"]}
        self.assertEqual((t["broken"]["rows"], t["broken"]["rows_unknown"], t["broken"]["kind"]), (0, True, "view"))
        self.assertNotIn("rows_unknown", t["items"])

    def test_no_data_folder_and_other_users(self):
        shutil.rmtree(self.data)
        self.assertEqual(self.get("db").json(), {"files": [], "file": None, "tables": []})
        other = User.objects.create_user("other", password=TEST_PASSWORD, is_staff=True)
        from rest_framework.test import APIClient

        c2 = APIClient(HTTP_X_KERN="1")
        c2.force_login(other)
        self.assertEqual(c2.get("/api/apps/hens/db").status_code, 404)
        self.assertEqual(c2.get("/api/apps/hens/tasks").status_code, 404)
        self.assertEqual(c2.post("/api/apps/hens/db/query", {"sql": "select 1"}, format="json").status_code, 404)

    # -- rows
    def test_rows_paging_order_blobs_and_long_text(self):
        r = self.get("db/rows?file=app.db&table=items&limit=3&offset=2&order=weight&dir=desc").json()
        self.assertEqual((r["total"], r["offset"], r["limit"]), (7, 2, 3))
        self.assertEqual(r["columns"], ["id", "name", "weight", "pic", "note"])
        self.assertEqual([row[1] for row in r["rows"]], ["hen 5", "hen 4", "hen 3"])
        self.assertEqual(r["rows"][0][3], {"blob": 1000})
        self.assertEqual(r["rows"][0][4], "short")
        self.assertEqual((len(r["rows"][2][4]), r["truncated_cells"]), (2000, [[2, 4, 5000]]))  # [row, column, full length]
        self.assertEqual(len(self.get("db/rows?table=items&limit=100000").json()["rows"]), 7)  # file chosen by itself
        self.assertEqual(self.get("db/rows?table=items&limit=2").json()["limit"], 2)
        self.assertEqual(self.get("db/rows?table=heavy").json()["total"], 3)

    def test_names_must_exist_and_are_never_trusted(self):
        for bad in ('nope', 'items" ; DROP TABLE items; --', "items; select 1", 'sqlite_master"'):
            self.assertEqual(self.get("db/rows?table=" + bad.replace(" ", "%20").replace(";", "%3B").replace('"', "%22")).status_code, 404, bad)
        r = self.get("db/rows?table=items&order=" + 'id"%3B DROP TABLE items')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.get("db/rows?table=items&dir=sideways").status_code, 400)
        self.assertEqual(self.get("db/rows?table=items&offset=x").status_code, 400)
        self.assertEqual(self.get("db/rows").status_code, 400)
        self.assertEqual(sha(self.db), self.before)

    # -- queries
    def test_select_and_caps(self):
        r = self.query("SELECT name, weight FROM items ORDER BY id LIMIT 2;").json()
        self.assertEqual((r["columns"], r["rows"], r["truncated"]), (["name", "weight"], [["hen 1", 0.5], ["hen 2", 1.0]], False))
        self.assertIsInstance(r["seconds"], float)
        r = self.query("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 1000) SELECT x FROM n").json()
        self.assertEqual((len(r["rows"]), r["truncated"]), (500, True))
        r = self.query("SELECT pic, note, 1e999 AS inf FROM items WHERE id = 3").json()
        self.assertEqual(r["rows"][0][0], {"blob": 1000})
        self.assertEqual((len(r["rows"][0][1]), r["truncated_cells"]), (2000, [[0, 1, 5000]]))
        self.assertEqual(r["rows"][0][2], "inf")  # JSON has no infinity
        self.assertEqual(self.query("EXPLAIN SELECT * FROM items").status_code, 200)
        r = self.query("PRAGMA table_info(items)").json()
        self.assertEqual(r["rows"][1][1], "name")
        self.assertEqual(self.query("  -- a comment\n select 1").status_code, 200)

    def test_nothing_can_be_written(self):
        for sql in ("DELETE FROM items", "UPDATE items SET name = 'x'", "INSERT INTO items (name) VALUES ('x')",
                    "DROP TABLE items", "CREATE TABLE t (x)", "VACUUM", "REINDEX",
                    "ATTACH DATABASE '" + str(self.outside / "evil.db") + "' AS evil",
                    "WITH x AS (SELECT 1) DELETE FROM items",
                    "EXPLAIN DELETE FROM items",
                    "SELECT 1; DELETE FROM items", "SELECT 1; SELECT 2",
                    "PRAGMA query_only = OFF", "PRAGMA writable_schema = ON", "PRAGMA journal_mode = DELETE",
                    "PRAGMA user_version = 5", "PRAGMA database_list", "SELECT * FROM pragma_database_list",
                    "SELECT load_extension('/lib/x86_64-linux-gnu/libm.so.6')", "SELECT writefile('/tmp/x', 'y')",
                    "", "   ", "select" + " " * 5 + ";" + "delete from items"):
            r = self.query(sql)
            self.assertEqual(r.status_code // 100, 4, (sql, r.status_code, r.content))
            self.assertEqual(sha(self.db), self.before, sql)
        # The same through the module, with the checks of the first word skipped: the authorizer alone stops it.
        con = dbexplore.connect(self.app.id, "app.db", dbexplore.Clock())
        for sql in ("DELETE FROM items", "PRAGMA query_only = OFF", "ATTACH ':memory:' AS m", "CREATE TABLE t (x)",
                    "UPDATE items SET name = 'x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                con.execute(sql)
        con.close()
        self.assertFalse((self.outside / "evil.db").exists())
        self.assertEqual(sha(self.db), self.before)
        self.assertEqual(self.query("SELECT count(*) FROM items").json()["rows"], [[7]])

    def test_slow_queries_are_stopped(self):
        with mock.patch.object(dbexplore, "TIME_CAP", 0.4):
            r = self.query("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("stopped", r.json()["detail"])

    def test_wal_database_in_a_folder_that_cannot_be_written(self):
        con = sqlite3.connect(self.data / "wal.db")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (x)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()  # a clean close removes -wal and -shm
        os.chmod(self.data, 0o555)
        try:
            self.assertEqual(self.query("SELECT x FROM t", "wal.db").json()["rows"], [[1]])
        finally:
            os.chmod(self.data, 0o755)

    # -- hostile data folders
    def test_symlinked_file_is_refused_and_not_listed(self):
        os.symlink(self.secret_db, self.data / "link.db")
        self.assertNotIn("link.db", [f["path"] for f in self.get("db").json()["files"]])
        for url in ("db?file=link.db", "db/rows?file=link.db&table=secrets"):
            r = self.get(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertNotIn("the-key", r.content.decode())
        r = self.query("SELECT v FROM secrets", "link.db")
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("the-key", r.content.decode())

    def test_symlinked_folder_component_is_refused(self):
        os.symlink(self.outside, self.data / "dir")
        self.assertEqual(self.get("db?file=dir/kern.sqlite3").status_code, 403)
        self.assertEqual(self.query("SELECT v FROM secrets", "dir/kern.sqlite3").status_code, 403)
        self.assertEqual([f["path"] for f in self.get("db").json()["files"]], ["app.db"])

    def test_swapped_data_folder_is_refused(self):
        # The app owns its home folder, so it can replace "data" by a link to anywhere.
        shutil.copy(self.secret_db, self.outside / "app.db")
        shutil.rmtree(self.data)
        os.symlink(self.outside, self.data)
        r = self.get("db")
        self.assertEqual(r.json(), {"files": [], "file": None, "tables": []})
        for r in (self.get("db?file=app.db"), self.get("db?file=kern.sqlite3"), self.query("SELECT v FROM secrets", "app.db")):
            self.assertEqual(r.status_code, 403)
            self.assertNotIn("the-key", r.content.decode())

    def test_swapped_home_folder_is_refused(self):
        home = core.home_dir(self.app.id)
        moved = home.with_name("home-real")
        home.rename(moved)
        os.symlink(moved, home)  # realpath(data) is no longer <apps>/<id>/home/data
        self.assertEqual(self.get("db?file=app.db").status_code, 403)

    def test_path_tricks(self):
        for f in ("../kern.sqlite3", "a/../app.db", "/etc/passwd", str(self.secret_db), "./app.db", "app.db/", "x\0y", "..",
                  "sub//app.db", "..\\app.db"):
            r = self.get("db?file=" + f.replace("\0", "%00").replace("\\", "%5C"))
            self.assertIn(r.status_code, (400, 403, 404), (f, r.status_code))
            self.assertNotIn("the-key", r.content.decode())
        self.assertEqual(self.get("db?file=missing.db").status_code, 404)
        self.assertEqual(self.get("db?file=" + "a/" * 300 + "x.db").status_code, 400)

    def test_files_of_another_owner_are_refused(self):
        # A hard link to a file of Kern's is owned by Kern, not by the app's user.
        real = os.lstat

        def fake(path, *a, **kw):
            st = real(path, *a, **kw)
            if str(path).endswith("app.db"):
                return types.SimpleNamespace(st_mode=st.st_mode, st_uid=st.st_uid + 1, st_size=st.st_size, st_dev=st.st_dev, st_ino=st.st_ino)
            return st

        with mock.patch.object(dbexplore.os, "lstat", fake):
            r = self.get("db?file=app.db")
        self.assertEqual(r.status_code, 403)
        self.assertIn("does not belong", r.json()["detail"])

    def test_planted_wal_or_journal_symlink_is_refused(self):
        for suffix in ("-wal", "-shm", "-journal"):
            os.symlink(self.secret_db, str(self.db) + suffix)
            self.assertEqual(self.get("db?file=app.db").status_code, 403, suffix)
            os.unlink(str(self.db) + suffix)
        self.assertEqual(self.get("db?file=app.db").status_code, 200)

    def test_fifo_and_non_database_files(self):
        os.mkfifo(self.data / "pipe.db")
        (self.data / "plain.txt").write_text("hello")
        (self.data / "fake.db").write_text("not sqlite at all")
        files = {f["path"]: f["is_sqlite"] for f in self.get("db").json()["files"]}  # must not hang on the FIFO
        self.assertEqual(files, {"app.db": True, "fake.db": False})
        self.assertEqual(self.get("db?file=pipe.db").status_code, 400)
        self.assertEqual(self.get("db?file=fake.db").status_code, 400)
        self.assertEqual(self.get("db?file=plain.txt").status_code, 400)

    def test_file_name_cannot_inject_uri_parameters(self):
        odd = self.data / "x?mode=rwc&y.db"
        shutil.copy(self.db, odd)
        before = sha(odd)
        self.assertEqual(self.query("SELECT count(*) FROM items", odd.name).json()["rows"], [[7]])
        self.assertEqual(self.query("WITH x AS (SELECT 1) DELETE FROM items", odd.name).status_code, 403)
        self.assertEqual(sha(odd), before)

    def test_file_swapped_after_the_check_is_caught(self):
        real_safe, real_sniff = dbexplore.safe_file, dbexplore._sniff

        def swap(path):
            ok = real_sniff(path)
            os.unlink(path)  # the app replaces the file after the checks, right before SQLite opens it
            os.symlink(self.secret_db, path)
            return ok

        with mock.patch.object(dbexplore, "_sniff", swap):
            r = self.query("SELECT v FROM secrets")
        self.assertEqual(r.status_code, 409, r.content)  # SQLite opened a file other than the one that was checked
        self.assertNotIn("the-key", r.content.decode())
        # ... and a swap between the path check and the header check is caught by the header check (no links followed).
        os.unlink(self.db)
        shutil.copy(self.outside / "kern.sqlite3", self.db)

        def swap_early(app_id, rel):
            path, st = real_safe(app_id, rel)
            os.unlink(path)
            os.symlink(self.secret_db, path)
            return path, st

        with mock.patch.object(dbexplore, "safe_file", swap_early):
            r = self.query("SELECT v FROM secrets")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertNotIn("the-key", r.content.decode())


# ---------------------------------------------------------------------------------------- tasks


class TasksTests(AppsRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.c = authed()
        self.user = User.objects.get(username="tester")
        self.app = App.objects.create(owner=self.user.id, slug="hens", name="Hens", secret="s", hook_secret="h", state="running")

    def test_shape_with_the_worker_up(self):
        now = deploy.timezone.now()
        Deployment.objects.create(app=self.app, number=1, status="live", finished=now)
        Deployment.objects.create(app=self.app, number=2, status="building", started=now, subject="Add chart", trigger="ai")
        Deployment.objects.create(app=self.app, number=3, status="queued", trigger="push")
        Deployment.objects.create(app=self.app, number=4, status="queued", trigger="manual")
        BuilderChat.objects.create(app=self.app, status="running", progress=[{"verb": "Read", "detail": "app.py"}])
        live = {"running": True, "pid": 77, "uptime": 120, "restarts": 2, "cpu": 3.5, "rss": 4096}
        procs = [{"pid": 77, "ppid": 1, "cmd": "python app.py", "cpu": 3.5, "mem_bytes": 4096, "age_s": 120}]
        with mock.patch.object(api, "worker_status", return_value={"apps": {str(self.app.id): live}}), \
                mock.patch.object(api, "worker_get", return_value={"processes": procs}) as wg:
            r = self.c.get("/api/apps/hens/tasks")
        self.assertEqual(r.status_code, 200, r.content)
        wg.assert_called_once_with(f"/processes/{self.app.id}")
        j = r.json()
        self.assertEqual(j["state"], "running")
        self.assertEqual(j["process"], {"pid": 77, "uptime_s": 120, "restarts": 2, "cpu": 3.5, "mem_bytes": 4096})
        self.assertEqual(j["processes"], procs)
        self.assertEqual(j["deploy"], {"number": 2, "status": "building", "started": now.isoformat(), "subject": "Add chart"})
        self.assertEqual(j["queued"], [{"number": 3, "status": "queued", "trigger": "push"},
                                        {"number": 4, "status": "queued", "trigger": "manual"}])
        self.assertEqual(j["builder"], {"status": "running", "step": "Read: app.py"})
        self.assertTrue(j["worker_up"])

    def test_degrades_when_the_worker_is_down(self):
        with mock.patch.object(api, "worker_status", return_value=None):
            j = self.c.get("/api/apps/hens/tasks").json()
        self.assertEqual((j["worker_up"], j["process"], j["processes"], j["deploy"], j["queued"], j["builder"]),
                         (False, None, [], None, [], None))
        # The worker answers /status but not /processes
        with mock.patch.object(api, "worker_status", return_value={"apps": {str(self.app.id): {"running": True, "pid": 5}}}), \
                mock.patch.object(api, "worker_get", return_value=None):
            j = self.c.get("/api/apps/hens/tasks").json()
        self.assertEqual((j["worker_up"], j["process"]["pid"], j["processes"]), (True, 5, []))

    def test_real_process_tree(self):
        from .supervisor import Instance, Runtime, Supervisor

        env = {**os.environ, "SECRET_TOKEN_FOR_TEST": "hunter2"}
        p = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30 & wait"], env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            sup = Supervisor()
            rt = Runtime(app={"id": 1})
            rt.current = Instance(1, 1, core.Plan(runtime="command"), Path(self.root), port=1,
                                  proc=types.SimpleNamespace(pid=p.pid, returncode=None))
            sup.apps[1] = rt
            deadline = __import__("time").time() + 5
            while __import__("time").time() < deadline and len(sup.processes(1)) < 3:
                __import__("time").sleep(0.1)
            procs = sup.processes(1)
            self.assertEqual(len(procs), 3, procs)
            self.assertEqual(procs[0]["pid"], p.pid)  # the root comes first
            self.assertEqual({q["ppid"] for q in procs[1:]}, {p.pid})
            self.assertEqual(sorted(q["cmd"] for q in procs[1:]), ["sleep 30", "sleep 30"])
            for q in procs:
                self.assertEqual(set(q), {"pid", "ppid", "cmd", "cpu", "mem_bytes", "age_s"})
                self.assertGreater(q["mem_bytes"], 0)
                self.assertLessEqual(len(q["cmd"]), 200)
            self.assertNotIn("hunter2", json.dumps(procs))  # command lines only, never the environment
            self.assertEqual(Supervisor().processes(1), [])
            rt.current = None
            self.assertEqual(sup.processes(1), [])
        finally:
            os.killpg(p.pid, 9)
            p.wait()

    def test_control_route_needs_the_token(self):
        from .supervisor import Supervisor

        async def run():
            sup = Supervisor()
            sup.processes = lambda app_id: [{"pid": app_id}]
            with mock.patch.object(core, "control_token", return_value="tok"):
                client = TestClient(TestServer(gateway.Control(sup).app()))
                await client.start_server()
                try:
                    self.assertEqual((await client.get("/processes/5")).status, 403)
                    r = await client.get("/processes/5", headers={"X-Kern-Control": "tok"})
                    self.assertEqual(await r.json(), {"processes": [{"pid": 5}]})
                finally:
                    await client.close()

        asyncio.run(run())


class BuilderToolTests(AppsRoot, TestCase):
    def setUp(self):
        super().setUp()
        self.user = authed() and User.objects.get(username="tester")
        self.app = App.objects.create(owner=self.user.id, slug="hens", name="Hens", secret="s", hook_secret="h")
        self.chat = BuilderChat.objects.create(app=self.app, status="running")
        self.sup = mock.Mock()
        self.sess = builder.Session(self.app, self.chat, types.SimpleNamespace(sup=self.sup))

    def test_tools_are_declared_and_dispatch(self):
        names = {t["name"] for t in builder.TOOLS}
        self.assertTrue({"query_db", "list_processes"} <= names)
        for n in names:
            self.assertTrue(callable(getattr(builder.Session, n)), n)
        self.assertIn("query_db", builder.SYSTEM)
        self.assertIn("list_processes", builder.SYSTEM)

    def test_query_db_reads_and_cannot_write(self):
        self.assertIn("no SQLite database", json.loads(builder._execute(self.sess, "query_db", {"sql": "select 1"}))["error"])
        d = core.data_dir(self.app.id)
        d.mkdir(parents=True)
        con = sqlite3.connect(d / "app.db")
        con.execute("CREATE TABLE t (x)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(300)])
        con.commit()
        con.close()
        before = sha(d / "app.db")
        out = json.loads(builder._execute(self.sess, "query_db", {"sql": "SELECT x FROM t"}))
        self.assertEqual((len(out["rows"]), out["truncated"], out["file"], out["columns"]), (100, True, "app.db", ["x"]))
        err = json.loads(builder._execute(self.sess, "query_db", {"sql": "DELETE FROM t", "file": "app.db"}))
        self.assertIn("error", err)
        self.assertIn("error", json.loads(builder._execute(self.sess, "query_db", {"sql": "select 1", "file": "../x"})))
        self.assertEqual(sha(d / "app.db"), before)

    def test_list_processes_is_what_the_tasks_endpoint_shows(self):
        self.sup.status.return_value = {"apps": {str(self.app.id): {"running": True, "pid": 9, "uptime": 3, "restarts": 0, "cpu": 1, "rss": 2}}}
        self.sup.processes.return_value = [{"pid": 9, "ppid": 1, "cmd": "node server.js", "cpu": 1, "mem_bytes": 2, "age_s": 3}]
        out = json.loads(builder._execute(self.sess, "list_processes", {}))
        self.assertEqual(set(out), set(tasks.build(self.app).keys()))
        self.assertEqual((out["process"]["pid"], out["processes"][0]["cmd"]), (9, "node server.js"))
