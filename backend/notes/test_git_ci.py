"""CI for hosted git repositories: pipeline parsing, triggers, the shell runner end to end (real git
client pushing to the live server), secrets, artifacts, and the Docker runner against a fake Docker API."""
import io
import json
import os
import shutil
import socketserver
import subprocess
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

from django.db import connections
from django.test import SimpleTestCase, override_settings

from kern import secretbox
from notes import ci, ci_pipeline as pl, ci_runner as rn
from notes import gitevents
from notes.models_ci import CISecret, Job, Run
from notes.test_git_hosting import GitLive
from notes.tests import authed

GOOD = """
jobs:
  test:
    steps:
      - run: echo hello from $KERN_REPO
"""


class PipelineParseTests(SimpleTestCase):
    def test_defaults_and_shorthand(self):
        p = pl.parse("on: push\njobs:\n  a:\n    steps: ['echo hi', {run: ls, name: List}]\n")
        self.assertEqual(p["on"], {"push": {"branches": ["*"], "tags": []}, "manual": False})
        self.assertTrue(pl.parse("jobs: {a: {steps: [x]}}")["on"]["manual"])  # no on section: everything
        self.assertEqual([s["name"] for s in p["jobs"][0]["steps"]], ["echo hi", "List"])
        self.assertTrue(pl.push_matches(p, "feature/x", None))
        self.assertFalse(pl.push_matches(p, None, "v1"))

    def test_on_key_is_true_in_yaml_11(self):
        p = pl.parse("on:\n  push: {branches: [main], tags: ['v*']}\n  manual: false\njobs: {a: {steps: [x]}}\n")
        self.assertFalse(p["on"]["manual"])
        self.assertTrue(pl.push_matches(p, "main", None))
        self.assertFalse(pl.push_matches(p, "dev", None))
        self.assertTrue(pl.push_matches(p, None, "v1.2"))
        self.assertFalse(pl.push_matches(p, None, "x1"))

    def test_job_if_and_inheritance(self):
        p = pl.parse("image: alpine\nenv: {A: 1}\njobs:\n  a:\n    if: {branch: main, tag: 'v*'}\n    env: {B: x}\n    steps: [x]\n")
        j = p["jobs"][0]
        self.assertEqual((j["image"], j["env"]), ("alpine", {"A": "1", "B": "x"}))
        self.assertTrue(pl.job_enabled(j, "main", None))
        self.assertTrue(pl.job_enabled(j, None, "v2"))
        self.assertFalse(pl.job_enabled(j, "dev", None))

    def test_errors_are_clear(self):
        cases = {
            "jobs: [": "Invalid YAML",
            "- a": "mapping",
            "jobs: {}": "at least one job",
            "jobz: {}": "unknown key",
            "jobs: {a: {steps: []}}": "at least one step",
            "jobs: {a: {steps: [{name: x}]}}": "run command",
            "jobs: {a: {needs: [b], steps: [x]}}": "no job named 'b'",
            "jobs: {a: {needs: [b], steps: [x]}, b: {needs: [a], steps: [x]}}": "circle",
            "jobs: {'a b': {steps: [x]}}": "job names",
            "jobs: {a: {steps: [x], timeout: -1}}": "positive number",
            "jobs: {a: {steps: [x], env: {KERN_X: 1}}}": "reserved",
            "jobs: {a: {steps: [x], secrets: ['a-b']}}": "valid secret name",
            "jobs: {a: {steps: [x], image: '-bad'}}": "valid image",
            "on: {push: {branch: x}}\njobs: {a: {steps: [x]}}": "unknown key",
            "jobs: {a: {steps: [x], if: main}}": "mapping",
        }
        for text, needle in cases.items():
            with self.assertRaises(pl.PipelineError, msg=text) as cm:
                pl.parse(text)
            self.assertIn(needle, str(cm.exception), text)

    def test_glob_and_order(self):
        rx = pl.glob_regex("dist/*.apk")
        self.assertTrue(pl.matches_path(rx, "dist/app.apk"))
        self.assertFalse(pl.matches_path(rx, "dist/sub/app.apk"))
        self.assertTrue(pl.matches_path(pl.glob_regex("**/*.apk"), "a/b/app.apk"))
        self.assertTrue(pl.matches_path(pl.glob_regex("dist"), "dist/a/b.txt"))
        p = pl.parse("jobs:\n  b: {needs: [a], steps: [x]}\n  a: {steps: [x]}\n")
        self.assertEqual([j["name"] for j in pl.order(p["jobs"])], ["a", "b"])


class LogMaskTests(SimpleTestCase):
    def test_secret_split_across_writes_is_masked(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        lg = rn.LogWriter(Path(d) / "x.log", ["hunter2-secret"])
        for part in [b"pass=hunt", b"er2-sec", b"ret and more\nline2 hunter2", b"-secret\n"]:
            lg.write(part)
        lg.line("[kern-ci] done")
        lg.close()
        out = (Path(d) / "x.log").read_text()
        self.assertNotIn("hunter2", out)
        self.assertIn("pass=*** and more", out)
        self.assertIn("line2 ***", out)
        self.assertIn("[kern-ci] done", out)

    def test_multiline_secret_lines_are_masked_individually(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        lg = rn.LogWriter(Path(d) / "x.log", ["-----BEGIN KEY-----\nabcdefgh\n-----END KEY-----"])
        lg.write(b"line abcdefgh\n")
        lg.close()
        self.assertNotIn("abcdefgh", (Path(d) / "x.log").read_text())


class CIBase(GitLive):
    ENV = {"KERN_CI_RUNNER": "shell"}

    def setUp(self):
        super().setUp()
        self.data = tempfile.mkdtemp(prefix="kern-ci-data-")
        self._data = override_settings(DATA_DIR=self.data)
        self._data.enable()
        secretbox.reset_for_tests()
        patcher = mock.patch.dict(os.environ, self.ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        gitevents._load()

    def tearDown(self):
        self._data.disable()
        secretbox.reset_for_tests()
        shutil.rmtree(self.data, ignore_errors=True)
        super().tearDown()

    def setup_repo(self, name, yml=GOOD, files=None, branch="main"):
        self.make_repo(name)
        work = self.workdir({".kern/ci.yml": yml, **(files or {})})
        self.run_git("push", "-q", self.url(name), f"main:{branch}", cwd=work)
        return work

    def runs(self, repo=None):
        qs = Run.objects.all() if repo is None else Run.objects.filter(repo=repo)
        return list(qs.order_by("id"))

    def log(self, run, job):
        return ci.log_path(run.id, job).read_text()

    def run_all(self):
        ci.drain()

    def job(self, run, name):
        return Job.objects.get(run=run, name=name)


class TriggerTests(CIBase):
    def test_push_queues_a_run_only_when_the_pipeline_matches(self):
        self.make_repo("plain")
        work = self.workdir()
        self.run_git("push", "-q", self.url("plain"), "main", cwd=work)
        self.assertEqual(self.runs(), [])  # no pipeline file

        yml = "on: {push: {branches: [main], tags: ['v*']}}\n" + GOOD
        work = self.setup_repo("app", yml)
        runs = self.runs("app")
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual((r.ref, r.status, r.trigger, r.pusher, r.subject), ("refs/heads/main", "queued", "push", "tester", "First"))
        self.assertEqual(len(r.sha), 40)
        self.assertEqual([j.name for j in r.jobs.all()], ["test"])

        self.run_git("push", "-q", self.url("app"), "main:feature", cwd=work)
        self.assertEqual(len(self.runs("app")), 1)  # branch not listed under on.push
        self.run_git("tag", "nope", cwd=work)
        self.run_git("tag", "v1", cwd=work)
        self.run_git("push", "-q", self.url("app"), "v1", cwd=work)
        self.assertEqual([x.ref for x in self.runs("app")], ["refs/heads/main", "refs/tags/v1"])
        self.run_git("push", "-q", self.url("app"), "nope", cwd=work)  # tag not matching v*
        self.assertEqual(len(self.runs("app")), 2)
        self.run_git("push", "-q", self.url("app"), ":feature", ":refs/tags/v1", cwd=work)  # deletions
        self.assertEqual(len(self.runs("app")), 2)

    def test_default_is_every_branch_but_no_tags(self):
        work = self.setup_repo("dflt", GOOD, branch="anything/goes")
        self.assertEqual(len(self.runs("dflt")), 1)
        self.run_git("tag", "v9", cwd=work)
        self.run_git("push", "-q", self.url("dflt"), "v9", cwd=work)
        self.assertEqual(len(self.runs("dflt")), 1)

    def test_yaml_extension_is_accepted_and_push_can_be_disabled(self):
        self.make_repo("y")
        work = self.workdir({".kern/ci.yaml": GOOD})
        self.run_git("push", "-q", self.url("y"), "main", cwd=work)
        self.assertEqual(len(self.runs("y")), 1)
        self.setup_repo("off", "on: {push: false}\n" + GOOD)
        self.assertEqual(self.runs("off"), [])

    def test_a_newer_push_supersedes_queued_runs_of_that_branch(self):
        work = self.setup_repo("sup")
        self.commit(work, {"a.txt": "1\n"})
        self.run_git("push", "-q", self.url("sup"), "main", cwd=work)
        self.run_git("push", "-q", self.url("sup"), "HEAD:other", cwd=work)
        self.commit(work, {"a.txt": "2\n"})
        self.run_git("push", "-q", self.url("sup"), "main", cwd=work)
        runs = self.runs("sup")
        self.assertEqual([(r.ref.split("/")[-1], r.status) for r in runs],
                         [("main", "cancelled"), ("main", "cancelled"), ("other", "queued"), ("main", "queued")])
        self.assertEqual(Job.objects.filter(run=runs[0]).first().status, "cancelled")

    def test_running_runs_are_not_superseded(self):
        work = self.setup_repo("sup2")
        run = self.runs("sup2")[0]
        Run.objects.filter(pk=run.pk).update(status="running")
        self.commit(work, {"a.txt": "1\n"})
        self.run_git("push", "-q", self.url("sup2"), "main", cwd=work)
        self.assertEqual(Run.objects.get(pk=run.pk).status, "running")

    def test_invalid_pipeline_becomes_an_error_run(self):
        self.setup_repo("bad", "jobs: [oops")
        (r,) = self.runs("bad")
        self.assertEqual(r.status, "error")
        self.assertIn(".kern/ci.yml: Invalid YAML", r.error)
        self.assertIsNotNone(r.finished)
        self.setup_repo("bad2", "jobs:\n  a:\n    needs: [zzz]\n    steps: [x]\n")
        self.assertIn("no job named 'zzz'", self.runs("bad2")[0].error)
        d = self.c.get(f"/api/git/repos/bad2/ci/runs/{self.runs('bad2')[0].id}").json()
        self.assertEqual((d["status"], d["jobs"]), ("error", []))


class ShellRunTests(CIBase):
    def test_jobs_needs_and_conditions(self):
        yml = """
env: {GREETING: hi}
jobs:
  build:
    steps:
      - name: Say
        run: echo "$GREETING from $KERN_REPO on $KERN_BRANCH @ ${KERN_SHA:0:7} run $KERN_RUN_ID ci=$KERN_CI"
      - run: ls README.md .kern/ci.yml
  test:
    needs: build
    steps: [{run: echo testing}]
  deploy:
    needs: [test]
    if: {branch: release}
    steps: [{run: echo deploying}]
  lint:
    steps: [{run: "echo linting; false"}]
  after_lint:
    needs: [lint]
    steps: [{run: echo never}]
"""
        self.setup_repo("pipe", yml, {"README.md": "# Hi\n"})
        self.run_all()
        (run,) = self.runs("pipe")
        self.assertEqual(run.status, "failed")
        got = {j.name: (j.status, j.exit_code) for j in run.jobs.all()}
        self.assertEqual(got, {"build": ("success", 0), "test": ("success", 0), "deploy": ("skipped", None),
                               "lint": ("failed", 1), "after_lint": ("skipped", None)})
        out = self.log(run, "build")
        self.assertIn("##[step 1/2] Say", out)
        self.assertIn(f"hi from pipe on main @ {run.sha[:7]} run {run.id} ci=1", out)
        self.assertIn("README.md", out)
        self.assertIn("linting", self.log(run, "lint"))
        self.assertIn("does not match", self.log(run, "deploy"))
        self.assertIn("needs lint", self.log(run, "after_lint"))
        self.assertIsNotNone(run.started)
        self.assertIsNotNone(run.finished)
        # Job order follows dependencies.
        self.assertEqual([j.name for j in run.jobs.all()][:2], ["build", "test"])

    def test_success_and_failing_step_stops_the_job(self):
        self.setup_repo("ok", GOOD)
        self.run_all()
        self.assertEqual(self.runs("ok")[0].status, "success")
        yml = "jobs:\n  t:\n    steps:\n      - run: echo one\n      - run: exit 3\n      - run: echo NOTREACHED\n"
        self.setup_repo("fail", yml)
        self.run_all()
        r = self.runs("fail")[0]
        j = self.job(r, "t")
        self.assertEqual((r.status, j.status, j.exit_code), ("failed", "failed", 3))
        self.assertIn("step 2 failed", j.note)
        out = self.log(r, "t")
        self.assertIn("one", out)
        self.assertNotIn("NOTREACHED", out)

    def test_branch_conditions_decide_per_ref(self):
        yml = "jobs:\n  a: {steps: ['echo a']}\n  rel:\n    if: {branch: 'release/*'}\n    steps: ['echo rel']\n"
        self.setup_repo("cond", yml, branch="release/1.0")
        self.run_all()
        self.assertEqual({j.name: j.status for j in self.runs("cond")[0].jobs.all()}, {"a": "success", "rel": "success"})

    def test_step_timeout_fails_the_job(self):
        yml = "jobs:\n  slow:\n    steps:\n      - run: echo start\n      - {run: sleep 30, timeout: 0.03}\n"
        self.setup_repo("to", yml)
        t0 = time.monotonic()
        self.run_all()
        self.assertLess(time.monotonic() - t0, 15)
        r = self.runs("to")[0]
        j = self.job(r, "slow")
        self.assertEqual((r.status, j.status), ("failed", "failed"))
        self.assertIn("step timed out", j.note)
        self.assertIn("step timed out", self.log(r, "slow"))

    def test_job_timeout_is_capped_by_the_maximum(self):
        yml = "jobs:\n  slow:\n    timeout: 600\n    steps: ['sleep 30']\n"
        self.setup_repo("cap", yml)
        with mock.patch.dict(os.environ, {"KERN_CI_MAX_TIMEOUT_MIN": "0.03"}):
            self.run_all()
        j = self.job(self.runs("cap")[0], "slow")
        self.assertEqual(j.status, "failed")
        self.assertIn("timed out", j.note)

    def test_checkout_is_the_pushed_commit_and_environment_is_clean(self):
        work = self.setup_repo("env", "jobs:\n  t:\n    steps:\n      - run: cat data.txt; echo \"[$KERN_LEAK]\"; pwd\n",
                               {"data.txt": "first\n"})
        self.commit(work, {"data.txt": "second\n"})
        self.run_git("push", "-q", self.url("env"), "main", cwd=work)
        with mock.patch.dict(os.environ, {"KERN_LEAK": "secret-from-kern"}):
            self.run_all()
        out = self.log(self.runs("env")[-1], "t")
        self.assertIn("second", out)
        self.assertIn("[]", out)
        self.assertNotIn("secret-from-kern", out)

    def test_cancel_queued_and_running(self):
        yml = "jobs:\n  t:\n    steps: ['echo started; sleep 60']\n  u:\n    needs: [t]\n    steps: ['echo x']\n"
        work = self.setup_repo("can", yml)
        (queued,) = self.runs("can")
        r = self.c.post(f"/api/git/repos/can/ci/runs/{queued.id}/cancel")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "cancelled")
        self.assertEqual(self.c.post(f"/api/git/repos/can/ci/runs/{queued.id}/cancel").status_code, 409)
        self.assertEqual(ci.drain(), 0)

        self.run_git("push", "-q", self.url("can"), "main:b2", cwd=work)
        run = self.runs("can")[-1]
        errors = []

        def canceller():
            try:
                for _ in range(200):
                    if Job.objects.filter(run_id=run.id, status="running").exists():
                        time.sleep(0.5)
                        r2 = authed().post(f"/api/git/repos/can/ci/runs/{run.id}/cancel")
                        if r2.status_code != 200:
                            errors.append(r2.content)
                        return
                    time.sleep(0.1)
                errors.append("never started")
            finally:
                connections.close_all()

        th = threading.Thread(target=canceller)
        th.start()
        t0 = time.monotonic()
        ci.drain()
        th.join()
        self.assertEqual(errors, [])
        self.assertLess(time.monotonic() - t0, 30)
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertEqual({j.name: j.status for j in run.jobs.all()}, {"t": "cancelled", "u": "cancelled"})
        self.assertIn("started", self.log(run, "t"))

    def test_manual_run_and_rerun(self):
        work = self.setup_repo("man", "on: {push: false}\n" + GOOD)
        self.assertEqual(self.runs("man"), [])
        r = self.c.post("/api/git/repos/man/ci/runs", {"ref": "main"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["trigger"], r.json()["pusher"], r.json()["status"]), ("manual", "tester", "queued"))
        self.assertEqual(self.c.post("/api/git/repos/man/ci/runs", {"ref": "nope"}, format="json").status_code, 404)
        self.assertEqual(self.c.post("/api/git/repos/man/ci/runs", {"ref": "--upload-pack=x"}, format="json").status_code, 400)
        rid = r.json()["id"]
        self.assertEqual(self.c.post(f"/api/git/repos/man/ci/runs/{rid}/rerun").status_code, 409)  # not finished
        self.run_all()
        r2 = self.c.post(f"/api/git/repos/man/ci/runs/{rid}/rerun")
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual((r2.json()["trigger"], r2.json()["sha"]), ("rerun", r.json()["sha"]))
        self.assertNotEqual(r2.json()["id"], rid)
        self.run_all()
        self.assertEqual([x.status for x in self.runs("man")], ["success", "success"])
        # Manual runs can be switched off, and need a pipeline file at all.
        self.setup_repo("nomanual", "on: {manual: false}\n" + GOOD)
        self.assertEqual(self.c.post("/api/git/repos/nomanual/ci/runs", {"ref": "main"}, format="json").status_code, 400)
        self.make_repo("empty")
        w = self.workdir()
        self.run_git("push", "-q", self.url("empty"), "main", cwd=w)
        self.assertEqual(self.c.post("/api/git/repos/empty/ci/runs", {"ref": "main"}, format="json").status_code, 400)

    def test_manual_run_of_a_broken_pipeline_is_an_error_run(self):
        self.setup_repo("mb", "on: {push: false}\njobs: {")
        r = self.c.post("/api/git/repos/mb/ci/runs", {"ref": "main"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status"], "error")

    def test_log_api_supports_offsets_and_status_per_sha(self):
        self.setup_repo("api", "jobs:\n  t:\n    steps: ['echo héllo wörld']\n")
        self.run_all()
        (run,) = self.runs("api")
        base = f"/api/git/repos/api/ci/runs/{run.id}"
        d = self.c.get(base).json()
        self.assertEqual((d["status"], d["jobs"][0]["name"], d["jobs"][0]["status"]), ("success", "t", "success"))
        full = self.c.get(f"{base}/jobs/t/log").json()
        self.assertIn("héllo wörld", full["text"])
        self.assertTrue(full["done"])
        self.assertEqual(full["offset"], full["size"])
        half = self.c.get(f"{base}/jobs/t/log?offset=0").json()["text"].encode().index("é".encode()) + 1
        rest = self.c.get(f"{base}/jobs/t/log?offset={half + 1}").json()
        self.assertEqual(rest["text"].encode(), full["text"].encode()[half + 1:])
        end = self.c.get(f"{base}/jobs/t/log?offset={full['size']}").json()
        self.assertEqual((end["text"], end["done"]), ("", True))
        self.assertEqual(self.c.get(f"{base}/jobs/zzz/log").status_code, 404)
        self.assertEqual(self.c.get("/api/git/repos/api/ci/runs/99999").status_code, 404)
        lst = self.c.get("/api/git/repos/api/ci/runs?ref=main").json()
        self.assertEqual([x["id"] for x in lst["runs"]], [run.id])
        self.assertEqual(self.c.get("/api/git/repos/api/ci/runs?ref=other").json()["runs"], [])
        st = self.c.get(f"/api/git/repos/api/ci/status?shas={run.sha},{'0' * 40},bogus").json()
        self.assertEqual(st, {run.sha: {"status": "success", "run": run.id}})
        pipe = self.c.get("/api/git/repos/api/ci/pipeline?ref=main").json()
        self.assertEqual((pipe["found"], pipe["jobs"], pipe["manual"]), (True, ["t"], True))

    def test_runs_of_one_repo_are_not_reachable_through_another(self):
        self.setup_repo("one")
        self.setup_repo("two")
        rid = self.runs("one")[0].id
        self.assertEqual(self.c.get(f"/api/git/repos/two/ci/runs/{rid}").status_code, 404)
        self.assertEqual(self.c.post(f"/api/git/repos/two/ci/runs/{rid}/cancel").status_code, 404)
        self.assertEqual(self.c.get(f"/api/git/repos/two/ci/runs/{rid}/jobs/test/log").status_code, 404)
        self.assertEqual(self.c.get("/api/git/repos/nonexist/ci/runs").status_code, 404)


class SecretsAndArtifactsTests(CIBase):
    def test_secrets_are_injected_masked_scoped_and_never_returned(self):
        yml = """
jobs:
  with:
    secrets: [DEPLOY_KEY]
    steps:
      - run: echo "key=$DEPLOY_KEY"; echo "split=${DEPLOY_KEY:0:5}"
  without:
    steps:
      - run: echo "other=[${DEPLOY_KEY:-unset}]"
"""
        self.setup_repo("sa", yml)
        self.setup_repo("sb", yml)
        for repo, value in (("sa", "s3cr3t-value-A"), ("sb", "s3cr3t-value-B")):
            r = self.c.put(f"/api/git/repos/{repo}/ci/secrets/DEPLOY_KEY", {"value": value}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertNotIn(value, r.content.decode())
        listing = self.c.get("/api/git/repos/sa/ci/secrets")
        self.assertEqual([s["name"] for s in listing.json()["secrets"]], ["DEPLOY_KEY"])
        self.assertNotIn("s3cr3t", listing.content.decode())
        self.assertNotIn("value", listing.json()["secrets"][0])
        self.assertNotIn("s3cr3t-value-A", CISecret.objects.get(repo="sa").value_enc)  # encrypted at rest
        self.run_all()
        ra, rb = self.runs("sa")[0], self.runs("sb")[0]
        out = self.log(ra, "with")
        self.assertIn("key=***", out)
        self.assertNotIn("s3cr3t-value-A", out)
        self.assertNotIn("s3cr3t-value-B", out)
        self.assertIn("other=[unset]", self.log(ra, "without"))
        # B's run got B's value (masked in its own log), never A's.
        self.assertIn("key=***", self.log(rb, "with"))
        self.assertEqual(secretbox.decrypt(CISecret.objects.get(repo="sb").value_enc), "s3cr3t-value-B")
        self.assertEqual(ci.secret_values("sa", ["DEPLOY_KEY"]), {"DEPLOY_KEY": "s3cr3t-value-A"})
        # API responses for the run contain no secret either.
        self.assertNotIn("s3cr3t", self.c.get(f"/api/git/repos/sa/ci/runs/{ra.id}").content.decode())

    def test_missing_secret_fails_the_job_with_a_message(self):
        self.setup_repo("ms", "jobs:\n  d:\n    secrets: [NOPE]\n    steps: ['echo x']\n")
        self.run_all()
        r = self.runs("ms")[0]
        self.assertEqual((r.status, self.job(r, "d").status), ("failed", "failed"))
        self.assertIn("NOPE", self.log(r, "d"))

    def test_secret_validation_and_delete(self):
        self.make_repo("sv")
        for name in ("bad-name", "1x", "KERN_X", "a" * 70):
            self.assertEqual(self.c.put(f"/api/git/repos/sv/ci/secrets/{name}", {"value": "v"}, format="json").status_code, 400, name)
        self.assertEqual(self.c.put("/api/git/repos/sv/ci/secrets/OK", {"value": ""}, format="json").status_code, 400)
        self.assertEqual(self.c.put("/api/git/repos/sv/ci/secrets/OK", {"value": "v"}, format="json").status_code, 200)
        self.assertEqual(self.c.delete("/api/git/repos/sv/ci/secrets/OK").status_code, 204)
        self.assertEqual(self.c.delete("/api/git/repos/sv/ci/secrets/OK").status_code, 404)

    def test_artifacts_are_collected_listed_and_downloadable(self):
        yml = """
jobs:
  build:
    artifacts: ["dist/*.txt", "out", "missing/*.zip"]
    steps:
      - run: mkdir -p dist out/deep && echo A > dist/a.txt && echo B > dist/b.bin && echo C > out/deep/c.txt && ln -s /etc/passwd dist/link.txt
  broken:
    artifacts: ["x.txt"]
    steps: ['echo X > x.txt; false']
"""
        self.setup_repo("art", yml)
        self.run_all()
        (run,) = self.runs("art")
        self.assertEqual(run.status, "failed")
        files = ci.run_artifacts(run)
        self.assertEqual(sorted((f.job, f.name) for f in files), [("build", "dist/a.txt"), ("build", "out/deep/c.txt")])
        self.assertTrue(all(f.path.is_file() and f.size == 2 for f in files))
        self.assertIn("matched no files", self.log(run, "build"))
        self.assertEqual(ci.run_artifacts(run.id), files)
        d = self.c.get(f"/api/git/repos/art/ci/runs/{run.id}").json()
        self.assertEqual(sorted(a["name"] for a in d["artifacts"]), ["dist/a.txt", "out/deep/c.txt"])
        r = self.c.get(f"/api/git/repos/art/ci/runs/{run.id}/artifacts/build/dist/a.txt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"A\n")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        for bad in ("build/dist/b.bin", "build/../../x", "build/dist/link.txt", "nojob/dist/a.txt", "x/y"):
            self.assertEqual(self.c.get(f"/api/git/repos/art/ci/runs/{run.id}/artifacts/{bad}").status_code, 404, bad)
        self.assertIsNone(ci.artifact_path(run.id, "build", "../build/dist/a.txt"))
        self.assertEqual(ci.run_artifacts(self.runs("art")[0].id + 1000), [])
        # Unfinished runs expose nothing.
        Run.objects.filter(pk=run.pk).update(status="running")
        self.assertEqual(ci.run_artifacts(run.id), [])


class LifecycleTests(CIBase):
    def test_crash_recovery_marks_running_runs_as_errors(self):
        self.setup_repo("rec")
        run = self.runs("rec")[0]
        Run.objects.filter(pk=run.pk).update(status="running")
        Job.objects.filter(run=run).update(status="running")
        extra = Job.objects.create(run=run, name="later", position=5)
        self.assertEqual(ci.recover(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, "error")
        self.assertIn("worker stopped", run.error)
        self.assertEqual(self.job(run, "test").status, "error")
        extra.refresh_from_db()
        self.assertEqual(extra.status, "skipped")
        self.assertEqual(ci.recover(), 0)
        # The worker does it at startup for every user.
        self.setup_repo("rec2")
        r2 = self.runs("rec2")[0]
        Run.objects.filter(pk=r2.pk).update(status="running")
        ci.Worker(runner_factory=rn.ShellRunner, poll=0).startup()
        self.assertEqual(Run.objects.get(pk=r2.pk).status, "error")

    def test_worker_claims_the_oldest_run_once(self):
        self.setup_repo("w1")
        self.setup_repo("w2")
        w = ci.Worker(runner_factory=rn.ShellRunner, poll=0)
        uid, run = w.next_run()
        self.assertEqual((run.repo, run.status), ("w1", "running"))
        _, run2 = w.next_run()
        self.assertEqual(run2.repo, "w2")
        self.assertIsNone(w.next_run())
        with mock.patch.dict(os.environ, {"KERN_CI_CONCURRENCY": "3"}):
            self.assertEqual(ci.concurrency(), 3)
        self.assertEqual(ci.concurrency(), 1)

    def test_retention_keeps_the_newest_runs_and_deletes_their_files(self):
        work = self.setup_repo("ret")
        with mock.patch.dict(os.environ, {"KERN_CI_KEEP_RUNS": "2"}):
            for i in range(3):
                ci.drain()
                self.commit(work, {"n.txt": f"{i}\n"})
                self.run_git("push", "-q", self.url("ret"), "main", cwd=work)
            ci.drain()
        runs = self.runs("ret")
        self.assertEqual(len(runs), 2)
        self.assertEqual(sorted(p.name for p in ci.ci_root().iterdir()), sorted(str(r.id) for r in runs))

    def test_deleting_the_repository_deletes_runs_logs_and_secrets(self):
        self.setup_repo("gone")
        self.c.put("/api/git/repos/gone/ci/secrets/TOKEN", {"value": "abcdef"}, format="json")
        self.run_all()
        run = self.runs("gone")[0]
        self.assertTrue(ci.run_dir(run.id).is_dir())
        self.assertEqual(self.c.delete("/api/git/repos/gone").status_code, 204)
        self.assertEqual(self.runs("gone"), [])
        self.assertFalse(ci.run_dir(run.id).exists())
        self.assertEqual(CISecret.objects.count(), 0)

    def test_api_needs_a_login(self):
        from rest_framework.test import APIClient

        self.make_repo("auth")
        self.assertIn(APIClient(HTTP_X_KERN="1").get("/api/git/repos/auth/ci/runs").status_code, (401, 403))


# ------------------------------------------------------------ fake Docker


class FakeDocker:
    """A tiny Docker Engine API on a unix socket. "Containers" are temp folders; execs really run the
    command with the local shell inside the unpacked workspace, so the whole path (upload tar, exec,
    multiplexed logs, copy artifacts out, remove) is exercised."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="kd")
        self.sock = os.path.join(self.dir, "docker.sock")
        self.images = {"alpine:3"}
        self.pulled = []
        self.containers = {}
        self.execs = {}
        self.calls = []
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):  # a client that gave up (timeout kill)
                    pass

            def address_string(self):
                return "unix"

            def reply(self, status, obj=None, raw=None, ctype="application/json"):
                data = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def route(self, method):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                path = unquote(u.path)
                fake.calls.append((method, path, q))
                fake.handle(self, method, path, q, body)

            do_GET = lambda self: self.route("GET")  # noqa: E731
            do_POST = lambda self: self.route("POST")  # noqa: E731
            do_PUT = lambda self: self.route("PUT")  # noqa: E731
            do_DELETE = lambda self: self.route("DELETE")  # noqa: E731

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        self.server = Server(self.sock, Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def handle(self, h, method, path, q, body):
        parts = path.strip("/").split("/")
        if path == "/_ping":
            return h.reply(200, raw=b"OK", ctype="text/plain")
        if parts[0] == "images":
            if parts[1] == "create":
                self.pulled.append(q["fromImage"])
                self.images.add(q["fromImage"])
                return h.reply(200, raw=b'{"status":"Pulling"}\n{"status":"Done"}\n')
            ref = "/".join(parts[1:-1])
            if ref in self.images:
                return h.reply(200, {"Id": "sha256:1"})
            return h.reply(404, {"message": f"No such image: {ref}"})
        if parts[0] == "containers" and parts[1] == "create":
            cid = os.urandom(8).hex()
            ws = os.path.join(self.dir, cid)
            os.makedirs(ws)
            cfg = json.loads(body)
            self.containers[cid] = {"cfg": cfg, "dir": ws, "name": q.get("name"), "killed": False, "procs": [], "removed": False}
            return h.reply(201, {"Id": cid})
        if parts[0] == "containers" and parts[1] == "json":
            out = [{"Id": cid, "Labels": c["cfg"]["Labels"]} for cid, c in self.containers.items() if not c["removed"] and c["cfg"]["Labels"].get("kern.ci") == "1"]
            return h.reply(200, out)
        if parts[0] == "containers":
            c = self.containers.get(parts[1])
            if c is None or (c["removed"] and method != "DELETE"):
                return h.reply(404, {"message": "No such container"})
            act = parts[2] if len(parts) > 2 else ""
            if method == "DELETE":
                c["removed"] = True
                self.kill(c)
                shutil.rmtree(c["dir"], ignore_errors=True)
                return h.reply(204)
            if act == "start":
                return h.reply(204)
            if act == "kill":
                c["killed"] = True
                self.kill(c)
                return h.reply(204)
            if act == "archive" and method == "PUT":
                with tarfile.open(fileobj=io.BytesIO(body)) as tf:
                    tf.extractall(c["dir"], filter="data")
                return h.reply(200, {})
            if act == "archive" and method == "GET":
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tf:
                    tf.add(os.path.join(c["dir"], "workspace"), arcname="workspace")
                return h.reply(200, raw=buf.getvalue(), ctype="application/x-tar")
            if act == "exec":
                eid = os.urandom(8).hex()
                self.execs[eid] = {"cfg": json.loads(body), "c": c, "code": None}
                return h.reply(201, {"Id": eid})
        if parts[0] == "exec":
            e = self.execs[parts[1]]
            if parts[2] == "json":
                return h.reply(200, {"Running": e["code"] is None, "ExitCode": e["code"]})
            if parts[2] == "start":
                return self.run_exec(h, e)
        h.reply(404, {"message": f"unhandled {method} {path}"})

    @staticmethod
    def kill(c):
        for p in c["procs"]:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                pass

    def run_exec(self, h, e):
        cfg, c = e["cfg"], e["c"]
        h.wfile.write(b"HTTP/1.1 101 UPGRADED\r\nContent-Type: application/vnd.docker.raw-stream\r\n"
                      b"Connection: Upgrade\r\nUpgrade: tcp\r\n\r\n")
        env = dict(x.split("=", 1) for x in cfg["Env"])
        env["PATH"] = os.environ["PATH"]
        wd = os.path.join(c["dir"], cfg["WorkingDir"].lstrip("/"))
        p = subprocess.Popen(cfg["Cmd"], cwd=wd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        c["procs"].append(p)
        try:
            while chunk := os.read(p.stdout.fileno(), 4096):
                h.wfile.write(bytes([1, 0, 0, 0]) + len(chunk).to_bytes(4, "big") + chunk)
            p.wait()
        except OSError:
            pass
        e["code"] = p.returncode if p.returncode >= 0 else 137
        h.close_connection = True


class DockerRunnerTests(CIBase):
    ENV = {"KERN_CI_RUNNER": "docker"}

    def setUp(self):
        super().setUp()
        self.fd = FakeDocker()
        self.addCleanup(self.fd.close)
        p = mock.patch.dict(os.environ, {"KERN_DOCKER_SOCKET": self.fd.sock})
        p.start()
        self.addCleanup(p.stop)

    def test_run_uploads_the_workspace_runs_steps_and_cleans_up(self):
        yml = """
image: python:3.13
jobs:
  build:
    secrets: [KEY]
    artifacts: ["dist/*.txt"]
    steps:
      - run: echo "in $KERN_REPO key=$KEY"; cat README.md
      - run: mkdir dist && echo built > dist/o.txt
  second:
    image: alpine:3
    needs: [build]
    steps: ['echo second']
"""
        self.setup_repo("dk", yml, {"README.md": "# Hi\n"})
        self.c.put("/api/git/repos/dk/ci/secrets/KEY", {"value": "dockersecret"}, format="json")
        self.run_all()
        (run,) = self.runs("dk")
        self.assertEqual(run.status, "success", [ci.log_path(run.id, j).read_text() for j in ("build", "second") if ci.log_path(run.id, j).exists()])
        # Image pulled once (alpine:3 was already there); one container per job, labelled and removed.
        self.assertEqual(self.fd.pulled, ["python:3.13"])
        created = [c for c in self.fd.containers.values()]
        self.assertEqual(len(created), 2)
        for c in created:
            self.assertTrue(c["removed"])
            self.assertEqual(c["cfg"]["Labels"]["kern.ci"], "1")
            self.assertEqual(c["cfg"]["Labels"]["kern.ci.repo"], "dk")
            self.assertEqual(c["cfg"]["WorkingDir"], "/workspace")
        self.assertEqual([c["cfg"]["Image"] for c in created], ["python:3.13", "alpine:3"])
        methods = [(m, p) for m, p, _ in self.fd.calls]
        self.assertIn(("PUT", f"/containers/{next(iter(self.fd.containers))}/archive"), methods)
        self.assertTrue(any(p.endswith("/archive") and m == "GET" for m, p in methods))  # artifacts copied out
        out = self.log(run, "build")
        self.assertIn("in dk key=***", out)
        self.assertNotIn("dockersecret", out)
        self.assertIn("# Hi", out)  # README.md came through the uploaded archive
        self.assertIn("second", self.log(run, "second"))
        self.assertEqual([(f.job, f.name) for f in ci.run_artifacts(run)], [("build", "dist/o.txt")])
        self.assertEqual(next(iter(ci.run_artifacts(run))).path.read_text(), "built\n")

    def test_failure_exit_code_and_timeout_kill_the_container(self):
        self.setup_repo("df", "jobs:\n  a:\n    steps: ['exit 5']\n")
        self.run_all()
        j = self.job(self.runs("df")[0], "a")
        self.assertEqual((j.status, j.exit_code), ("failed", 5))
        self.setup_repo("dt", "jobs:\n  a:\n    steps:\n      - {run: sleep 30, timeout: 0.03}\n")
        t0 = time.monotonic()
        self.run_all()
        self.assertLess(time.monotonic() - t0, 15)
        j = self.job(self.runs("dt")[0], "a")
        self.assertEqual(j.status, "failed")
        self.assertIn("timed out", j.note)
        self.assertTrue(any(p.endswith("/kill") for _, p, _ in self.fd.calls))
        self.assertTrue(all(c["removed"] for c in self.fd.containers.values()))

    def test_docker_errors_become_error_jobs_and_stale_containers_are_removed(self):
        self.setup_repo("de", GOOD)
        shutil.rmtree(self.fd.dir)  # the daemon disappears
        self.fd.server.shutdown()
        self.run_all()
        r = self.runs("de")[0]
        self.assertEqual((r.status, self.job(r, "test").status), ("error", "error"))
        self.assertIn("Docker", self.job(r, "test").note)

    def test_cleanup_stale_removes_labelled_containers(self):
        self.fd.containers["abc"] = {"cfg": {"Labels": {"kern.ci": "1"}}, "dir": self.fd.dir + "/abc", "removed": False, "procs": []}
        self.fd.containers["other"] = {"cfg": {"Labels": {}}, "dir": self.fd.dir + "/o", "removed": False, "procs": []}
        n = ci.Worker().startup() or rn.DockerRunner().cleanup_stale()
        self.assertEqual(n, 0)  # startup() already removed it
        self.assertTrue(self.fd.containers["abc"]["removed"])
        self.assertFalse(self.fd.containers["other"]["removed"])


class CIPublishTests(CIBase):
    """A successful tag run attaches `release: true` jobs' artifacts to the tag's release, and every
    finished run is announced to webhooks as "ci_run"."""

    YML = """
on: {push: {branches: [main], tags: ['v*']}}
jobs:
  build:
    release: true
    artifacts: [dist/*]
    steps:
      - run: mkdir -p dist && echo apk > dist/app.apk
  notes:
    artifacts: [notes.txt]
    steps: ['echo n > notes.txt']
"""

    def test_tag_run_publishes_artifacts_and_emits(self):
        from notes import git_releases, gitwebhooks
        work = self.setup_repo("pub", self.YML)
        self.run_git("tag", "v1.0", cwd=work)
        self.run_git("push", "-q", self.url("pub"), "v1.0", cwd=work)
        from django.contrib.auth.models import User
        from kern import tenancy
        with mock.patch.object(gitwebhooks, "emit") as emit, tenancy.use(User.objects.get(username="tester").id):
            self.run_all()  # the worker runs each user's queue inside their tenant
        branch_run, tag_run = self.runs("pub")
        self.assertEqual((branch_run.status, tag_run.status), ("success", "success"))
        rel = git_releases.Release.objects.get(repo="pub", tag="v1.0")
        self.assertEqual([a.filename for a in rel.assets.all()], ["app.apk"])  # only the release: true job
        self.assertIn("attached 1 file(s) to the release of v1.0", self.log(tag_run, "build"))
        self.assertFalse(git_releases.Release.objects.filter(repo="pub").exclude(tag="v1.0").exists())
        events = [c.args[2] for c in emit.call_args_list]
        self.assertEqual(events.count("ci_run"), 2)
        payload = [c.args[3] for c in emit.call_args_list if c.args[2] == "ci_run"][-1]()
        self.assertEqual(payload["run"]["ref"], "refs/tags/v1.0")
        self.assertIn("ci_run", gitwebhooks.EVENTS)

    def test_release_flag_must_be_boolean(self):
        with self.assertRaises(pl.PipelineError):
            pl.parse("jobs: {a: {steps: [x], release: yes please}}")
