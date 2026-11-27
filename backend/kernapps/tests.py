"""Apps: names and routes, the build plan, the gateway's rules, the API, and a real deployment of a
template run by the supervisor and served through the gateway."""
import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from notes.tests import TEST_PASSWORD, authed

from . import core, deploy, gateway, isolation, source
from .models import App, Deployment

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
                    App.objects.filter(pk=app.pk).update(start_cmd="python -c 'raise SystemExit(3)'"),
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
