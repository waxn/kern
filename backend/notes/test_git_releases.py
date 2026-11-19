import hashlib
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from . import git_releases
from .models_git_releases import Release, ReleaseAsset
from .tests import authed


class ReleaseBase:
    """A temporary data folder and git root, a signed-in client and a repo "proj" with one commit."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="kern-rel-test-"))
        self._o = override_settings(KERN_GIT_ROOT=str(self.tmp / "git"), DATA_DIR=self.tmp / "data")
        self._o.enable()
        (self.tmp / "data").mkdir()
        self.c = authed()
        self.assertEqual(self.c.post("/api/git/repos", {"name": "proj"}, format="json").status_code, 201)
        self.path = self.tmp / "git" / "proj.git"
        self.commit_to_repo()

    def tearDown(self):
        self._o.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def commit_to_repo(self):
        work = self.tmp / "work"
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com",
               "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}

        def run(*a):
            subprocess.run(["git", *a], cwd=work, env=env, check=True, capture_output=True)
        work.mkdir()
        run("init", "-q", "-b", "main")
        (work / "a.txt").write_text("hi\n")
        run("add", "-A")
        run("commit", "-qm", "First")
        run("branch", "dev")
        run("push", "-q", str(self.path), "main", "dev")

    def tags(self):
        out = subprocess.run(["git", f"--git-dir={self.path}", "tag"], capture_output=True, text=True).stdout
        return out.split()

    def url(self, rest=""):
        return f"/api/git/repos/proj/releases{rest}"

    def new(self, tag="v1", **kw):
        r = self.c.post(self.url(), {"tag": tag, "target": "main", **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def upload(self, rid, *files):
        return self.c.post(self.url(f"/{rid}/assets"), {"files": [SimpleUploadedFile(n, d) for n, d in files]},
                           format="multipart")


class ReleaseApiTests(ReleaseBase, TestCase):
    def test_create_with_new_tag(self):
        r = self.new("v1", title="One", notes="# Hi", target="dev")
        self.assertEqual(self.tags(), ["v1"])
        self.assertEqual(r["title"], "One")
        self.assertFalse(r["tag_missing"])
        self.assertTrue(r["published"])
        self.assertEqual(self.c.get("/api/git/repos/proj").json()["tag_list"][0]["name"], "v1")

    def test_existing_tag_and_duplicate(self):
        subprocess.run(["git", f"--git-dir={self.path}", "tag", "old", "main"], check=True)
        self.new("old")
        self.assertEqual(self.tags(), ["old"])
        r = self.c.post(self.url(), {"tag": "old"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Release.objects.count(), 1)

    def test_bad_tag_names_and_targets(self):
        for t in ["", "-x", "a b", "a..b", "a~1", "x.lock", "/a", "a/", "a@{b", "a\\b", "v1\n", "x" * 300, None, 5]:
            r = self.c.post(self.url(), {"tag": t, "target": "main"}, format="json")
            self.assertEqual(r.status_code, 400, repr(t))
        r = self.c.post(self.url(), {"tag": "v2", "target": "nope"}, format="json")
        self.assertEqual(r.status_code, 404)
        r = self.c.post(self.url(), {"tag": "v2", "target": "--output=x"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.tags(), [])
        self.assertEqual(Release.objects.count(), 0)

    def test_empty_repo_cannot_tag(self):
        self.c.post("/api/git/repos", {"name": "empty"}, format="json")
        r = self.c.post("/api/git/repos/empty/releases", {"tag": "v1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.post("/api/git/repos/nope/releases", {"tag": "v1"}, format="json").status_code, 404)

    def test_patch_list_and_delete(self):
        a, b = self.new("v1"), self.new("v2")
        self.assertEqual([x["tag"] for x in self.c.get(self.url()).json()], ["v2", "v1"])
        r = self.c.patch(self.url(f"/{a['id']}"), {"title": "T", "notes": "n", "prerelease": True}, format="json")
        self.assertEqual((r.json()["title"], r.json()["notes"], r.json()["prerelease"]), ("T", "n", True))
        self.assertEqual(self.c.delete(self.url(f"/{a['id']}")).status_code, 204)
        self.assertEqual(self.tags(), ["v1", "v2"])  # tag kept by default
        self.assertEqual(self.c.delete(self.url(f"/{b['id']}?delete_tag=1")).status_code, 204)
        self.assertEqual(self.tags(), ["v1"])
        self.assertEqual(self.c.get(self.url(f"/{b['id']}")).status_code, 404)

    def test_latest_ignores_drafts_and_prereleases(self):
        self.assertEqual(self.c.get(self.url("/latest")).status_code, 404)
        one = self.new("v1")
        self.new("v2", draft=True)
        self.new("v3", prerelease=True)
        self.assertEqual(self.c.get(self.url("/latest")).json()["id"], one["id"])
        d = Release.objects.get(tag="v2")
        r = self.c.patch(self.url(f"/{d.id}"), {"draft": False}, format="json").json()
        self.assertTrue(r["published"])
        self.assertEqual(self.c.get(self.url("/latest")).json()["tag"], "v2")

    def test_tag_deleted_marks_missing(self):
        r = self.new("v1")
        subprocess.run(["git", f"--git-dir={self.path}", "tag", "-d", "v1"], check=True, capture_output=True)
        self.assertTrue(self.c.get(self.url(f"/{r['id']}")).json()["tag_missing"])
        self.assertTrue(self.c.get(self.url()).json()[0]["tag_missing"])

    def test_upload_download_and_replace(self):
        rid = self.new()["id"]
        data = os.urandom(3 * 1024 * 1024)
        r = self.upload(rid, ("../../evil/.hidden name.bin", data), ("b.txt", b"bee"))
        self.assertEqual(r.status_code, 201, r.content)
        assets = {a["filename"]: a for a in r.json()["assets"]}
        self.assertEqual(set(assets), {"b.txt", "hidden name.bin"})
        a = assets["hidden name.bin"]
        self.assertEqual(a["size"], len(data))
        self.assertEqual(a["sha256"], hashlib.sha256(data).hexdigest())
        stored = self.tmp / "data" / "git-releases" / "proj" / str(rid) / "hidden name.bin"
        self.assertTrue(stored.is_file())
        self.assertEqual(os.listdir(stored.parent).count("evil"), 0)

        d = self.c.get(a["url"])
        self.assertEqual(d.status_code, 200)
        self.assertEqual(b"".join(d.streaming_content), data)
        self.assertTrue(d["Content-Disposition"].startswith("attachment; filename*=UTF-8''hidden%20name.bin"))
        self.assertEqual(d["X-Content-Type-Options"], "nosniff")
        self.assertEqual(d["Content-Security-Policy"], "default-src 'none'; sandbox")
        self.assertEqual(d["Accept-Ranges"], "bytes")
        d.close()
        self.assertEqual(ReleaseAsset.objects.get(pk=a["id"]).downloads, 1)

        p = self.c.get(a["url"], HTTP_RANGE="bytes=10-19")
        self.assertEqual(p.status_code, 206)
        self.assertEqual(b"".join(p.streaming_content), data[10:20])
        self.assertEqual(p["Content-Range"], f"bytes 10-19/{len(data)}")
        self.assertEqual(self.c.get(a["url"], HTTP_RANGE="bytes=-5").status_code, 206)
        self.assertEqual(self.c.get(a["url"], HTTP_RANGE=f"bytes={len(data)}-").status_code, 416)
        self.assertEqual(ReleaseAsset.objects.get(pk=a["id"]).downloads, 1)  # partial reads do not count

        r = self.upload(rid, ("b.txt", b"new bee!"))
        self.assertEqual(len(r.json()["assets"]), 2)
        self.assertEqual(stored.with_name("b.txt").read_bytes(), b"new bee!")
        self.assertEqual([f for f in os.listdir(stored.parent) if f.startswith(".")], [])

        r = self.c.delete(self.url(f"/{rid}/assets/{a['id']}"))
        self.assertEqual([x["filename"] for x in r.json()["assets"]], ["b.txt"])
        self.assertFalse(stored.exists())
        self.assertEqual(self.c.get(a["url"]).status_code, 404)

    def test_upload_size_limit(self):
        rid = self.new()["id"]
        with mock.patch.dict(os.environ, {"KERN_RELEASE_MAX_BYTES": "100"}):
            self.assertEqual(self.upload(rid, ("ok.bin", b"x" * 100)).status_code, 201)
            r = self.upload(rid, ("big.bin", b"x" * 101))
            self.assertEqual(r.status_code, 413)
            # the streaming writer refuses too, and leaves nothing behind
            rel = Release.objects.get(pk=rid)
            with self.assertRaises(git_releases.ReleaseError):
                git_releases.store_file(rel, "big2.bin", iter([b"x" * 60, b"x" * 60]))
        d = self.tmp / "data" / "git-releases" / "proj" / str(rid)
        self.assertEqual(os.listdir(d), ["ok.bin"])
        self.assertEqual(self.upload(rid).status_code, 400)

    def test_filename_sanitising(self):
        f = git_releases.safe_filename
        self.assertEqual(f("a/b\\c.txt"), "c.txt")
        self.assertEqual(f("..."), "file")
        self.assertEqual(f(".env"), "env")
        self.assertEqual(f("a\x00b\n.txt"), "ab.txt")
        self.assertEqual(f(""), "file")
        long = f("n" * 500 + ".tar.gz")
        self.assertLessEqual(len(long.encode()), 200)
        self.assertTrue(long.endswith(".gz"))

    def test_attach_file_api(self):
        subprocess.run(["git", f"--git-dir={self.path}", "tag", "v9", "main"], check=True)
        src = self.tmp / "build.zip"
        src.write_bytes(b"zipdata")
        a = git_releases.attach_file("proj", "v9", "app.zip", src, title="Nine")
        rel = Release.objects.get(tag="v9")
        self.assertEqual((rel.title, rel.draft, bool(rel.published)), ("Nine", False, True))
        self.assertEqual(a.size, 7)
        self.assertTrue(src.exists())
        src.write_bytes(b"zipdata2")
        b = git_releases.attach_file("proj", "v9", "app.zip", src, move=True)
        self.assertEqual(b.pk, a.pk)
        self.assertEqual(b.size, 8)
        self.assertFalse(src.exists())
        self.assertEqual(rel.assets.count(), 1)
        self.assertEqual([r.tag for r in git_releases.releases_for("proj")], ["v9"])
        src.write_bytes(b"x")
        with self.assertRaises(git_releases.ReleaseError):
            git_releases.attach_file("proj", "nope", "x", src)  # no such tag
        with self.assertRaises(git_releases.ReleaseError):
            git_releases.attach_file("proj", "v9b", "x", src, create=False)

    def test_repo_deletion_removes_releases_and_files(self):
        rid = self.new()["id"]
        self.upload(rid, ("a.bin", b"1"))
        base = self.tmp / "data" / "git-releases" / "proj"
        self.assertTrue(base.exists())
        self.assertEqual(self.c.delete("/api/git/repos/proj").status_code, 204)
        self.assertFalse(base.exists())
        self.assertEqual(Release.objects.count(), 0)
        self.assertEqual(ReleaseAsset.objects.count(), 0)


class ReleaseBackupTests(ReleaseBase, TransactionTestCase):
    def test_backup_round_trip_includes_release_files(self):
        import zipfile
        from django.conf import settings
        from . import backup
        old_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = self.tmp / "media"
        settings.MEDIA_ROOT.mkdir()
        try:
            with mock.patch.object(backup, "BACKUP_DIR", self.tmp / "backups"):
                rid = self.new()["id"]
                self.upload(rid, ("app.bin", b"binary-data"))
                made = backup.create("manual")
                with zipfile.ZipFile(self.tmp / "backups" / made["name"]) as z:
                    self.assertIn(f"git-releases/proj/{rid}/app.bin", z.namelist())
                f = self.tmp / "data" / "git-releases" / "proj" / str(rid) / "app.bin"
                f.unlink()
                f.with_name("stray.bin").write_bytes(b"stray")
                self.c.delete(self.url(f"/{rid}"))
                backup.restore(self.tmp / "backups" / made["name"])
                self.assertEqual(f.read_bytes(), b"binary-data")
                self.assertFalse(f.with_name("stray.bin").exists())
                a = ReleaseAsset.objects.get(filename="app.bin")
                d = self.c.get(f"/api/git/repos/proj/releases/{rid}/assets/{a.id}/download")
                self.assertEqual(b"".join(d.streaming_content), b"binary-data")
        finally:
            settings.MEDIA_ROOT = old_media
