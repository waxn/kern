"""Push mirrors: after every push, copy a repository's branches and tags to a remote (e.g. GitHub,
so GitHub Actions can run there too).

What is pushed::

    git push --porcelain --prune <url> +refs/heads/*:refs/heads/* +refs/tags/*:refs/tags/*

rather than ``git push --mirror``: ``--mirror`` also copies every other ref (``refs/pull/*``,
``refs/notes/*``, whatever a repository grew), which hosted remotes such as GitHub refuse; this
mirrors exactly branches and tags, force-updates them and, because of ``--prune``, deletes
remote branches and tags that no longer exist here. With a branch filter ("only protected
branches" or patterns) the branches are listed one by one, so only those are pushed and branch
deletions are not propagated; tags are still mirrored with pruning.

SECURITY
- The URL must be https (http only to a local address, when the administrator allows local
  remotes) and carry no credentials; see :mod:`notes.remote_guard` for the address check.
- The username and token/password are stored encrypted (``kern.secretbox``). They reach git
  through an ``http.extraHeader`` entry in the process *environment*, never in argv, the URL or
  the repository's config, and are scrubbed from anything stored.
- Redirects are not followed, git is pinned to the addresses that passed the check, and a
  repository with no branches or tags is never pushed (``--prune`` would empty the remote).
"""
import base64
import fnmatch
import logging
import subprocess
import threading

from django.utils import timezone

from kern import secretbox, tenancy

from . import gitevents
from . import gitrepo as g
from . import remote_guard
from .models_git_hooks import GitMirror

log = logging.getLogger(__name__)

PUSH_TIMEOUT = 600  # seconds for one push
MAX_ERROR = 1200

_lock = threading.Lock()
_running: set[tuple] = set()
_dirty: set[tuple] = set()


# ----------------------------------------------------------------- helpers


def parse_filter(value: str) -> list[str]:
    return [p for p in (value or "").replace(",", " ").split() if p]


def clean_filter(value) -> str:
    pats = parse_filter(str(value or ""))
    if len(pats) > 20:
        raise g.GitError("Use at most 20 branch patterns.")
    for p in pats:
        if len(p) > 100 or p.startswith("-") or any(c in p for c in "\0:~^\\"):
            raise g.GitError("Invalid branch pattern.")
    return " ".join(pats)


def scrub(text: str, secrets=()) -> str:
    """Remove credentials from text before it is stored or shown."""
    import re

    for s in secrets:
        if s and len(s) >= 3:
            text = text.replace(s, "***")
    text = re.sub(r"(?i)authorization:[^\r\n]*", "Authorization: ***", text)
    return re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1***@", text)


def refspecs(mirror: GitMirror, path) -> list[str]:
    """What to push for this mirror's branch settings."""
    patterns = parse_filter(mirror.branch_filter)
    rules = [r["pattern"] for r in g.protected(path)] if mirror.only_protected else None
    tags = "+refs/tags/*:refs/tags/*"
    if not patterns and rules is None:
        return ["+refs/heads/*:refs/heads/*", tags]
    specs = []
    for b in g.branches(path):
        name = b["name"]
        if patterns and not any(fnmatch.fnmatchcase(name, p) for p in patterns):
            continue
        if rules is not None and not any(fnmatch.fnmatchcase(name, p) for p in rules):
            continue
        specs.append(f"+refs/heads/{name}:refs/heads/{name}")
    return specs + [tags]


def _run(cmd, env, timeout):
    """The one place a push process starts (tests wrap it to look at argv and environment)."""
    return subprocess.run(cmd, capture_output=True, env=env, timeout=timeout)


def _git_env(info: dict, username: str, secret: str) -> dict:
    env = g.env({"GIT_ALLOW_PROTOCOL": "https:http" if info["scheme"] == "http" else "https"})
    extra = {
        "http.followRedirects": "false",
        "http.lowSpeedLimit": "1000",
        "http.lowSpeedTime": "60",
        "credential.helper": "",
        "http.curloptResolve": f"{info['host']}:{info['port']}:{','.join(info['addrs'])}",
    }
    if secret:
        raw = f"{username or 'git'}:{secret}".encode()
        extra["http.extraHeader"] = "Authorization: Basic " + base64.b64encode(raw).decode()
    n = int(env["GIT_CONFIG_COUNT"])
    for i, (k, v) in enumerate(extra.items(), start=n):
        env[f"GIT_CONFIG_KEY_{i}"] = k
        env[f"GIT_CONFIG_VALUE_{i}"] = v
    env["GIT_CONFIG_COUNT"] = str(n + len(extra))
    return env


def push_once(mirror: GitMirror) -> str | None:
    """Push now. Returns None on success or a (credential free) error message."""
    secret = ""
    try:
        if mirror.secret_enc:
            secret = secretbox.decrypt(mirror.secret_enc)
    except secretbox.SecretBoxError:
        return "The stored token couldn't be decrypted. Enter it again."
    secrets = [secret, mirror.username, base64.b64encode(f"{mirror.username or 'git'}:{secret}".encode()).decode()]
    try:
        info = remote_guard.check_url(mirror.url, http="local")
        path = g.repo_path(mirror.repo)
        specs = refspecs(mirror, path)
        if not gitevents.snapshot(path):
            return None  # nothing to mirror; never prune a remote empty
    except (remote_guard.RemoteNotAllowed, g.GitError) as e:
        return scrub(str(e), secrets)
    cmd = ["git", f"--git-dir={path}", "push", "--porcelain", "--prune", "--", info["url"], *specs]
    try:
        r = _run(cmd, _git_env(info, mirror.username, secret), PUSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "The push took too long and was stopped."
    except OSError as e:
        return scrub(f"Couldn't run git: {e}", secrets)
    out = r.stdout.decode(errors="replace")
    err = r.stderr.decode(errors="replace")
    if r.returncode == 0:
        return None
    parts = []
    for ln in out.splitlines():
        cols = ln.split("\t")
        if ln.startswith("!") and len(cols) >= 3:
            parts.append(f"{cols[1].split(':')[0]}: {cols[2]}")
    msg = "\n".join(parts + [err.strip()]).strip() or "git push failed."
    return scrub(msg, secrets)[-MAX_ERROR:]


# ------------------------------------------------------------ run + coalesce


def sync_once(mirror_id: int) -> None:
    m = GitMirror.objects.filter(id=mirror_id).first()
    if m is None or not m.enabled:
        return
    GitMirror.objects.filter(id=m.id).update(last_attempt=timezone.now())
    try:
        error = push_once(m)
    except Exception as e:  # never leave a mirror stuck without a result
        log.exception("mirror %s failed", m.id)
        error = f"Unexpected error: {type(e).__name__}"
    if error:
        GitMirror.objects.filter(id=m.id).update(last_error=error)
    else:
        GitMirror.objects.filter(id=m.id).update(last_error="", last_success=timezone.now())


def _loop(key, mirror_id):
    try:
        while True:
            try:
                sync_once(mirror_id)
            except Exception:
                log.exception("mirror sync crashed")
            with _lock:
                if key in _dirty:  # another push arrived meanwhile: one more run, not one per push
                    _dirty.discard(key)
                    continue
                _running.discard(key)
                return
    finally:
        with _lock:
            _running.discard(key)
        if threading.current_thread() is not threading.main_thread() and not tenancy.testing():
            tenancy.close_connections()


def request_sync(mirror_id: int, block: bool = False) -> str:
    """Sync a mirror, coalescing: while one run is going, further requests only mark it dirty and
    cause a single extra run afterwards. Returns "started" or "queued". With ``block`` the run
    happens in the calling thread (when this call starts it)."""
    key = (tenancy.current_uid(), mirror_id)
    with _lock:
        if key in _running:
            _dirty.add(key)
            return "queued"
        _running.add(key)
    if block:
        _loop(key, mirror_id)
    else:
        tenancy.spawn(_loop, key, mirror_id)
    return "started"


def is_syncing(mirror_id: int) -> bool:
    with _lock:
        return (tenancy.current_uid(), mirror_id) in _running


@gitevents.on_push
def _on_push(event):
    for m in GitMirror.objects.filter(repo=event.repo, enabled=True):
        request_sync(m.id, block=tenancy.testing())
