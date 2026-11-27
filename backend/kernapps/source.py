"""Getting an app's code: from the owner's Kern repository or from a git URL, and writing commits to a
Kern repository (templates, the file editor and the AI builder all commit through :func:`commit`).

Everything that touches a Kern repository runs with the owner's tenant active (``tenancy.use``).
"""
from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from kern import tenancy
from notes import gitevents, gitmirrors, remote_guard
from notes import gitrepo as g

from . import core, isolation

FETCH_TIMEOUT = 300
MAX_FILE = 2 * 1024 * 1024  # bytes one commit may write per file (editor, AI)


class SourceError(Exception):
    pass


def mirror_path(app) -> Path:
    return core.app_dir(app.id) / "src.git"


def _scrub(msg: str, app) -> str:
    tok = core.get_token(app)
    return gitmirrors.scrub(msg, [tok]) if tok else msg


def fetch_url(app) -> Path:
    """Bring the mirror of a git-URL source up to date. Returns its path."""
    try:
        info = remote_guard.check_url(app.git_url, http="local")
    except remote_guard.RemoteNotAllowed as e:
        raise SourceError(str(e))
    path = mirror_path(app)
    env = gitmirrors._git_env(info, "x-access-token", core.get_token(app))
    if not (path / "HEAD").is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "init", "--bare", "--quiet", "--template=", str(path)], capture_output=True, env=env)
        if r.returncode:
            raise SourceError("Could not prepare the mirror: " + r.stderr.decode(errors="replace")[:300])
    cmd = ["git", f"--git-dir={path}", "fetch", "--prune", "--no-tags", "--depth=50", "--", info["url"],
           f"+refs/heads/{app.branch}:refs/heads/{app.branch}"]
    try:
        r = subprocess.run(cmd, capture_output=True, env=env, timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SourceError("Fetching the repository took too long.")
    if r.returncode:
        err = r.stderr.decode(errors="replace").strip()
        if "couldn't find remote ref" in err or "not found" in err.lower() and "branch" in err.lower():
            raise SourceError(f"The repository has no branch “{app.branch}”.")
        raise SourceError(_scrub("git fetch failed: " + err[-600:], app))
    return path


def git_dir(app, fetch: bool = True) -> Path:
    if app.source == "url":
        return fetch_url(app) if fetch else mirror_path(app)
    with tenancy.use(app.owner):
        try:
            return g.repo_path(app.repo)
        except g.GitError:
            raise SourceError(f"The repository “{app.repo}” does not exist any more.")


def _git(path: Path, *args, timeout=60) -> str:
    r = subprocess.run(["git", f"--git-dir={path}", *args], capture_output=True, env=_env(), timeout=timeout)
    if r.returncode:
        raise SourceError(r.stderr.decode(errors="replace").strip()[:500] or "git failed.")
    return r.stdout.decode(errors="replace")


def _env() -> dict:
    e = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
         "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "HOME": "/nonexistent"}
    import os
    e["PATH"] = os.environ.get("PATH", e["PATH"])
    return e


def resolve(app, path: Path, ref: str | None = None) -> tuple[str, str]:
    """(sha, subject) of the branch (or ``ref``)."""
    ref = ref or app.branch
    try:
        sha = _git(path, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()
    except SourceError:
        raise SourceError(f"There is no branch “{ref}” yet. Push some code to it first.")
    subject = _git(path, "log", "-1", "--format=%s", sha).strip()
    return sha, subject[:300]


def export(app, path: Path, sha: str, dest: Path) -> None:
    """Write the files of ``sha`` (only the app's sub-folder) into ``dest``, as the app's own user."""
    tree = f"{sha}:{app.subdir.strip('/')}" if app.subdir.strip("/") else sha
    archive = subprocess.Popen(["git", f"--git-dir={path}", "archive", "--format=tar", "--end-of-options", tree],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env())
    isolation.run_as(app.id, ["mkdir", "-p", str(dest)], check=False)
    try:
        r = subprocess.run(isolation.wrap(["tar", "-x", "--no-same-owner", "--no-same-permissions", "-C", str(dest)], app.id),
                           stdin=archive.stdout, capture_output=True, timeout=600,
                           env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    finally:
        archive.stdout.close()
        err = archive.stderr.read().decode(errors="replace")
        archive.wait()
    if archive.returncode:
        if "not a tree object" in err or "Not a valid object name" in err:
            raise SourceError(f"The folder “{app.subdir}” does not exist in this commit.")
        raise SourceError("Could not read the commit: " + err.strip()[:300])
    if r.returncode:
        raise SourceError("Could not unpack the files: " + r.stderr.decode(errors="replace").strip()[:300])


# ------------------------------------------------------------------ reading files


def clean_rel(p: str) -> str:
    p = str(p or "").replace("\\", "/").strip().strip("/")
    parts = PurePosixPath(p).parts
    if not p or any(x in ("..", ".", "") for x in parts) or p.startswith(".git/") or p == ".git" or len(p) > 400:
        raise SourceError(f"“{p}” is not a valid file path.")
    return p


def _full(app, rel: str) -> str:
    sub = app.subdir.strip("/")
    return f"{sub}/{rel}" if sub else rel


def list_files(app, path: Path, sha: str) -> list[dict]:
    sub = app.subdir.strip("/")
    tree = f"{sha}:{sub}" if sub else sha
    try:
        out = _git(path, "ls-tree", "-r", "-l", "-z", "--end-of-options", tree)
    except SourceError:
        return []
    files = []
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob":
            continue
        size = int(parts[3]) if parts[3].isdigit() else 0
        files.append({"path": name, "size": size, "mode": parts[0]})
    files.sort(key=lambda f: f["path"])
    return files


def read_file(app, path: Path, sha: str, rel: str) -> bytes | None:
    rel = clean_rel(rel)
    r = subprocess.run(["git", f"--git-dir={path}", "cat-file", "blob", f"{sha}:{_full(app, rel)}"],
                       capture_output=True, env=_env(), timeout=30)
    return r.stdout if r.returncode == 0 else None


# ---------------------------------------------------------------------- commits


def commit(app, changes: dict[str, bytes | str | None], message: str, author: str, pusher: str) -> str:
    """Commit ``changes`` (path → new content, or None to delete) on the app's branch of its Kern repository,
    then run Kern's push bookkeeping (CI, mirrors, webhooks and auto-deploy see it like any push).
    Paths are relative to the app's folder. Returns the new commit's sha."""
    if app.source != "kern":
        raise SourceError("This app's code comes from a git URL. Change it there and push; Kern will deploy it.")
    import os
    import tempfile

    with tenancy.use(app.owner):
        try:
            path = g.repo_path(app.repo)
        except g.GitError:
            raise SourceError(f"The repository “{app.repo}” does not exist any more.")
        before = gitevents.snapshot(path)
        ref = f"refs/heads/{app.branch}"
        parent = before.get(ref, "")
        fd, index = tempfile.mkstemp(prefix="kern-app-index-")
        os.close(fd)
        os.unlink(index)
        env = {**g.env(), "GIT_INDEX_FILE": index}

        def run(*args, input=None):
            r = subprocess.run(["git", f"--git-dir={path}", *args], input=input, capture_output=True, env=env, timeout=60)
            if r.returncode:
                raise SourceError(r.stderr.decode(errors="replace").strip()[:400] or "git failed.")
            return r.stdout.decode().strip()

        try:
            if parent:
                run("read-tree", parent)
            for rel, content in changes.items():
                full = _full(app, clean_rel(rel))
                if content is None:
                    run("update-index", "--force-remove", "--", full)
                    continue
                data = content.encode() if isinstance(content, str) else content
                if len(data) > MAX_FILE:
                    raise SourceError(f"{rel} is larger than {MAX_FILE // 1024 // 1024} MB.")
                blob = run("hash-object", "-w", "--stdin", input=data)
                mode = "100755" if data.startswith(b"#!") else "100644"
                run("update-index", "--add", "--cacheinfo", f"{mode},{blob},{full}")
            tree = run("write-tree")
            if parent and tree == run("rev-parse", f"{parent}^{{tree}}"):
                return parent  # nothing changed
            name = (author or "Kern")[:100]
            cenv = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": "apps@kern.local",
                    "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": "apps@kern.local"}
            r = subprocess.run(["git", f"--git-dir={path}", "commit-tree", tree, *(["-p", parent] if parent else []),
                                "-m", (message or "Update app").strip()[:2000]],
                               capture_output=True, env={**env, **cenv}, timeout=60)
            if r.returncode:
                raise SourceError(r.stderr.decode(errors="replace").strip()[:400])
            sha = r.stdout.decode().strip()
            run("update-ref", ref, sha, parent or "0" * 40)
        finally:
            try:
                os.unlink(index)
            except OSError:
                pass
        gitevents.after_push(app.owner, app.repo, path, before, pusher, "kern")
        return sha
