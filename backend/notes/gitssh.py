"""Git over SSH: a small asyncssh server that only speaks ``git-upload-pack`` / ``git-receive-pack``.

Run it with ``python manage.py ssh_server`` (docker-compose.yml "ssh" service). Clients sign in
with a public key registered in Settings (``accounts.SSHKey``): an account key reaches every
repository of its owner, a deploy key a single one (read-only or read/write). There are no
passwords, no shell, no port forwarding, no SFTP/SCP.

Everything blocking (Django ORM, repository checks, ``after_push``) runs in worker threads; git
itself runs as an asyncio subprocess with the same locked-down environment (``g.env()``) as the
HTTP protocol, and its stdin/stdout/stderr are piped to the SSH channel.
"""
import asyncio
import json
import logging
import os
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import asyncssh
from django.conf import settings
from django.db import connections
from django.utils import timezone

from accounts import site, throttle
from accounts.models import SSHKey
from kern import tenancy

from . import gitevents
from . import gitrepo as g

log = logging.getLogger(__name__)

SERVICES = ("git-upload-pack", "git-receive-pack")
HEARTBEAT_EVERY = 30  # seconds
HEARTBEAT_FRESH = 120  # the web app treats the server as running while the heartbeat is this recent
FAIL_LIMIT = 30  # unauthenticated connections per address before it is locked out for a while
MAX_GIT_PROCESSES = 32
PROTOCOL_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789=:;_.,-")


# ------------------------------------------------------------------ host key, heartbeat


def host_key_path() -> Path:
    return Path(settings.DATA_DIR) / "secrets" / "ssh_host_ed25519_key"


def load_host_key(path: Path | None = None):
    """The server's ed25519 host key; created on first use and kept in DATA_DIR/secrets."""
    path = path or host_key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = asyncssh.generate_private_key("ssh-ed25519").export_private_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another process won the race
            pass
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
    return asyncssh.read_private_key(path)


def fingerprint(key) -> str:
    return key.get_fingerprint("sha256")


def heartbeat_path() -> Path:
    return Path(settings.DATA_DIR) / "ssh-server.json"


def write_heartbeat(port: int, fp: str) -> None:
    p = heartbeat_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"time": time.time(), "port": port, "fingerprint": fp, "pid": os.getpid()}))
    os.replace(tmp, p)


def status() -> dict | None:
    """The running server's heartbeat ({"fingerprint", "port", …}), or None when no server is up.
    The web app uses this to know whether SSH clone URLs make sense."""
    try:
        beat = json.loads(heartbeat_path().read_text())
        if time.time() - float(beat["time"]) <= HEARTBEAT_FRESH:
            return beat
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


# ------------------------------------------------------------------ blocking helpers


# One worker thread for all the blocking work: it is brief (a key lookup, a ref snapshot), and it
# keeps this process from contending with itself for SQLite's write lock.
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kern-ssh")


def _in_thread(fn):
    """Run a blocking function in the worker thread; its database connections are closed afterwards."""

    async def run(*a):
        def call():
            try:
                return fn(*a)
            finally:
                connections.close_all()
        return await asyncio.get_running_loop().run_in_executor(_pool, call)

    run.__name__ = fn.__name__
    return run


@dataclass(frozen=True)
class Ident:
    key_id: int
    uid: int
    username: str
    title: str
    repo: str  # "" for an account key
    read_only: bool
    fingerprint: str


def _lookup(fp: str) -> Ident | None:
    """The identity a key fingerprint stands for, or None when it may not sign in."""
    k = SSHKey.objects.select_related("user").filter(fingerprint=fp).first()
    if k is None or not k.user.is_active or not site.get_all()["allow_git"]:
        return None
    return Ident(k.id, k.user_id, k.user.username, k.title, k.repo, k.read_only, fp)


lookup = _in_thread(_lookup)


@_in_thread
def _ip_locked(ip: str) -> bool:
    return bool(throttle.locked(f"ssh:ip:{ip}"))


@_in_thread
def _ip_failed(ip: str) -> None:
    throttle.fail(f"ssh:ip:{ip}", FAIL_LIMIT)


class Refuse(Exception):
    """A request we turn down with a message for the git client."""


def parse_command(command: str) -> tuple[str, str]:
    """(service, path argument) of ``git-upload-pack '<path>'`` and friends; anything else is refused."""
    try:
        parts = shlex.split(command or "")
    except ValueError:
        raise Refuse("Invalid command.")
    if len(parts) == 3 and parts[0] == "git" and parts[1] in ("upload-pack", "receive-pack"):
        return f"git-{parts[1]}", parts[2]
    if len(parts) == 2 and parts[0] in SERVICES:
        return parts[0], parts[1]
    raise Refuse("Kern only supports git-upload-pack and git-receive-pack over SSH.")


def parse_repo(arg: str, username: str) -> str:
    """The repository name in 'name.git', '/name.git', 'name' or '<username>/name.git'."""
    a = arg[1:] if arg.startswith("/") else arg
    if a.endswith(".git"):
        a = a[:-4]
    if "/" in a:
        owner, _, a = a.partition("/")
        if owner.lower() != username.lower():
            raise Refuse("Repository not found.")
    if not g.valid_name(a):
        raise Refuse("Invalid repository name.")
    return a


@dataclass
class Job:
    uid: int
    name: str
    path: Path
    service: str
    before: dict | None
    pusher: str
    env: dict  # g.env() of the owner's tenant (it needs the tenant, which the event loop doesn't have)


def _prepare(ident: Ident, service: str, arg: str) -> Job:
    """Check that this key may run ``service`` on the repository and locate it. Raises Refuse."""
    name = parse_repo(arg, ident.username)
    if ident.repo and ident.repo != name:  # a deploy key never reaches another repository
        raise Refuse("Repository not found.")
    pushing = service == "git-receive-pack"
    with tenancy.use(ident.uid):
        try:
            path = g.repo_path(name)
        except g.GitError:
            raise Refuse("Repository not found.")
        if pushing and ident.read_only:
            raise Refuse("This deploy key is read-only: it can fetch but not push.")
        before = gitevents.snapshot(path) if pushing else None
        env = g.env()
    SSHKey.objects.filter(pk=ident.key_id).update(last_used=timezone.now())
    return Job(ident.uid, name, path, service, before, f"key:{ident.title}", env)


prepare = _in_thread(_prepare)


def _finish_push(job: Job) -> None:
    with tenancy.use(job.uid):
        gitevents.after_push(job.uid, job.name, job.path, job.before, pusher=job.pusher, via="ssh")


finish_push = _in_thread(_finish_push)


# ------------------------------------------------------------------ the SSH server


class Server(asyncssh.SSHServer):
    def connection_made(self, conn):
        self.conn = conn
        peer = conn.get_extra_info("peername")
        self.ip = str(peer[0])[:64] if peer else "?"
        self.attempted = False
        self.locked = False
        self.candidate: Ident | None = None
        self.authed = False

    def connection_lost(self, exc):
        if self.attempted and not self.authed:
            asyncio.ensure_future(self._count_failure())

    async def _count_failure(self):
        try:
            await _ip_failed(self.ip)
        except Exception as e:
            log.warning("could not record a failed ssh sign-in: %s", e)

    async def begin_auth(self, username):
        self.attempted = True
        try:
            self.locked = await _ip_locked(self.ip)
        except Exception as e:
            log.warning("could not check the ssh sign-in throttle: %s", e)
        return True  # authentication is always required

    def public_key_auth_supported(self):
        return True

    def password_auth_supported(self):
        return False

    def kbdint_auth_supported(self):
        return False

    async def validate_public_key(self, username, key):
        # asyncssh checks the signature right after this returns, so the last key accepted here
        # is the one that signs in.
        if self.locked:
            return False
        try:
            ident = await lookup(key.get_fingerprint("sha256"))
        except Exception:
            log.exception("ssh key lookup failed")
            return False
        self.candidate = ident
        return ident is not None

    def auth_completed(self):
        self.authed = True
        self.conn.set_extra_info(kern_ident=self.candidate)
        log.info("ssh: %s signed in with key %r from %s", self.candidate.username, self.candidate.title, self.ip)


_slots = None


def _say(process, text: str, err=True):
    (process.stderr if err else process.stdout).write(text.encode() + b"\n")


async def handle(process):
    """One SSH session: run the git command the client asked for, or explain what is not offered."""
    global _slots
    ident: Ident | None = process.get_extra_info("kern_ident")
    if ident is None:
        process.exit(1)
        return
    if process.subsystem or process.command is None:
        # A plain `ssh git@host` (shell request), or an SFTP subsystem we do not provide.
        _say(process, f"Hi {ident.username}! Kern does not provide shell access.", err=False)
        process.exit(1)
        return
    try:
        service, arg = parse_command(process.command)
        current = await lookup(ident.fingerprint)  # the key may have been removed since sign-in
        if current is None:
            raise Refuse("This key is no longer allowed to sign in.")
        job = await prepare(current, service, arg)
    except Refuse as e:
        _say(process, f"Kern: {e}")
        process.exit(1)
        return
    except Exception:
        log.exception("ssh command failed to start")
        _say(process, "Kern: something went wrong on the server.")
        process.exit(1)
        return
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_GIT_PROCESSES)
    async with _slots:
        rc = await run_git(process, job)
    if job.service == "git-receive-pack" and rc == 0:
        try:
            await finish_push(job)
        except Exception:
            log.exception("post-push work failed for %s", job.name)
    process.exit(rc)


async def run_git(process, job: Job) -> int:
    extra = {}
    proto = process.env.get("GIT_PROTOCOL", "")
    if isinstance(proto, str) and 0 < len(proto) <= 100 and set(proto) <= PROTOCOL_OK:
        extra["GIT_PROTOCOL"] = proto  # the only variable we take from the client
    proc = await asyncio.create_subprocess_exec(
        "git", job.service[len("git-"):], str(job.path),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**job.env, **extra}, limit=1 << 20)

    async def feed():  # client -> git
        try:
            while True:
                data = await process.stdin.read(65536)
                if not data:
                    break
                proc.stdin.write(data)
                await proc.stdin.drain()
        except (ConnectionError, asyncssh.Error, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    async def pump(src, dst):  # git -> client
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, asyncssh.Error, OSError):
            proc.kill()

    tasks = [asyncio.ensure_future(feed()),
             asyncio.ensure_future(pump(proc.stdout, process.stdout)),
             asyncio.ensure_future(pump(proc.stderr, process.stderr))]
    try:
        rc = await proc.wait()
        await asyncio.gather(*tasks[1:], return_exceptions=True)  # let the last output through
    finally:
        tasks[0].cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return rc if rc >= 0 else 1


async def serve(host: str, port: int, host_key=None):
    """Start listening; returns the asyncssh acceptor (``.get_port()``, ``.close()``)."""
    return await asyncssh.listen(
        host, port, server_factory=Server, server_host_keys=[host_key or load_host_key()],
        process_factory=handle, encoding=None,
        password_auth=False, kbdint_auth=False, public_key_auth=True, gss_host=None,
        agent_forwarding=False, x11_forwarding=False, allow_scp=False,
        login_timeout=30, keepalive_interval=60)


async def run(host: str, port: int, stop: asyncio.Event) -> None:
    key = load_host_key()
    fp = fingerprint(key)
    acceptor = await serve(host, port, key)
    log.info("ssh: listening on %s:%s, host key %s (ssh-ed25519)", host, acceptor.get_port(), fp)
    try:
        while not stop.is_set():
            try:
                write_heartbeat(acceptor.get_port(), fp)
            except OSError:
                log.exception("could not write the ssh heartbeat")
            try:
                await asyncio.wait_for(stop.wait(), HEARTBEAT_EVERY)
            except asyncio.TimeoutError:
                pass
    finally:
        acceptor.close()
        heartbeat_path().unlink(missing_ok=True)
