"""imaplib-backed MailServer implementation (TLS only)."""

from __future__ import annotations

import imaplib
import re
import socket
import ssl
from datetime import datetime, timezone

from . import utf7
from .base import Fetched, FolderInfo, SelectInfo, ServerError

imaplib._MAXLINE = 10_000_000  # large UID SEARCH responses on big folders

_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$', re.IGNORECASE)
_UID_RE = re.compile(rb"\bUID\s+(\d+)", re.IGNORECASE)
_FLAGS_RE = re.compile(rb"\bFLAGS\s+\(([^)]*)\)", re.IGNORECASE)
_DATE_RE = re.compile(rb'\bINTERNALDATE\s+"([^"]+)"', re.IGNORECASE)
_MODSEQ_RE = re.compile(rb"\bMODSEQ\s+\((\d+)\)", re.IGNORECASE)
_COPYUID_RE = re.compile(rb"(\d+)\s+([\d:,]+)\s+([\d:,]+)")


def _unquote(raw: bytes) -> str:
    raw = raw.strip()
    if raw.startswith(b'"') and raw.endswith(b'"'):
        raw = re.sub(rb"\\(.)", rb"\1", raw[1:-1])
    return raw.decode("utf-8", "replace")


def _quote(name: str) -> str:
    enc = utf7.encode(name)
    return '"' + enc.replace("\\", "\\\\").replace('"', '\\"') + '"'


def uid_set(uids: list[int]) -> str:
    """Compress [1,2,3,7] -> '1:3,7'."""
    uids = sorted(set(uids))
    out, start, prev = [], None, None
    for u in uids:
        if start is None:
            start = prev = u
        elif u == prev + 1:
            prev = u
        else:
            out.append(f"{start}:{prev}" if start != prev else str(start))
            start = prev = u
    if start is not None:
        out.append(f"{start}:{prev}" if start != prev else str(start))
    return ",".join(out)


def expand_set(spec: bytes) -> list[int]:
    out = []
    for part in spec.split(b","):
        if b":" in part:
            a, b = part.split(b":")
            lo, hi = sorted((int(a), int(b)))
            out.extend(range(lo, hi + 1))
        elif part.strip():
            out.append(int(part))
    return out


def parse_list_response(data: list) -> list[FolderInfo]:
    folders = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):  # name sent as a literal
            head, literal = item
            m = _LIST_RE.match(head.strip())
            if not m:
                continue
            name = literal.decode("utf-8", "replace")
        else:
            m = _LIST_RE.match(item.strip())
            if not m:
                continue
            name = _unquote(m.group("name"))
        delim = m.group("delim")
        delimiter = "" if delim.upper() == b"NIL" else _unquote(delim)
        flags = [f.decode() for f in m.group("flags").split()]
        folders.append(FolderInfo(utf7.decode(name), delimiter, flags))
    return folders


def parse_fetch(data: list, want_body: bool) -> list[tuple[int, list[str], datetime | None, bytes | None, int | None]]:
    """Parse imaplib FETCH output into (uid, flags, internaldate, body, modseq)."""
    results = []
    i = 0
    while i < len(data):
        item = data[i]
        body = None
        if isinstance(item, tuple):
            meta = item[0]
            body = item[1]
            # Trailing items after the literal (e.g. ' FLAGS (\\Seen))').
            if i + 1 < len(data) and isinstance(data[i + 1], bytes):
                meta += b" " + data[i + 1]
                i += 1
        elif isinstance(item, bytes):
            meta = item
        else:
            i += 1
            continue
        i += 1
        um = _UID_RE.search(meta)
        if not um:
            continue
        if want_body and body is None:
            continue  # unsolicited FETCH (e.g. a flag change) mixed into the reply
        fm = _FLAGS_RE.search(meta)
        flags = [f.decode("utf-8", "replace") for f in fm.group(1).split()] if fm else []
        dm = _DATE_RE.search(meta)
        date = None
        if dm:
            try:
                date = datetime.strptime(dm.group(1).decode(), "%d-%b-%Y %H:%M:%S %z").astimezone(timezone.utc)
            except ValueError:
                date = None
        mm = _MODSEQ_RE.search(meta)
        results.append((int(um.group(1)), flags, date, body, int(mm.group(1)) if mm else None))
    return results


class ImapClient:
    def __init__(self, host: str, port: int, username: str, password: str, *, verify_tls: bool = True,
                 timeout: float = 60, use_tls: bool = True):
        """use_tls=False exists only for the protocol tests (mail/testing/imapd.py);
        production always uses implicit TLS."""
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            if use_tls:
                self.conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=timeout)
            else:
                self.conn = imaplib.IMAP4(host, port, timeout=timeout)
            self.conn.login(username, password)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ServerError(f"IMAP connect/login failed: {exc}") from exc
        caps = self._ok(self.conn.capability())[0]
        self.capabilities = {c.decode().upper() for c in (caps or b"").split()}
        if "ENABLE" in self.capabilities and "CONDSTORE" in self.capabilities:
            try:
                self.conn.enable("CONDSTORE")
            except imaplib.IMAP4.error:
                pass
        self._selected: str | None = None
        self._readonly = True

    def _ok(self, resp):
        typ, data = resp
        if typ != "OK":
            raise ServerError(f"IMAP error: {typ} {data!r}"[:500])
        return data

    def _call(self, fn, *args):
        try:
            return self._ok(fn(*args))
        except imaplib.IMAP4.abort as exc:
            raise OSError(f"IMAP connection lost: {exc}") from exc
        except imaplib.IMAP4.error as exc:
            raise ServerError(str(exc)) from exc

    def list_folders(self):
        return parse_list_response(self._call(self.conn.list))

    def select(self, name, readonly=True):
        data = self._call(self.conn.select, _quote(name), readonly)
        exists = int(data[0]) if data and data[0] and data[0].isdigit() else 0

        def code(key):
            resp = self.conn.untagged_responses.get(key)
            val = resp[-1] if resp else None
            if isinstance(val, bytes):
                m = re.match(rb"(\d+)", val)
                return int(m.group(1)) if m else None
            return None

        validity = code("UIDVALIDITY")
        if validity is None:
            raise ServerError(f"no UIDVALIDITY for {name}")
        self._selected, self._readonly = name, readonly
        return SelectInfo(validity, code("UIDNEXT"), exists, code("HIGHESTMODSEQ"))

    def _writable(self):
        if self._selected and self._readonly:
            self.select(self._selected, readonly=False)

    def search_uids(self):
        data = self._call(self.conn.uid, "SEARCH", None, "ALL")
        return [int(x) for x in (data[0] or b"").split()]

    def fetch_full(self, uids):
        if not uids:
            return []
        data = self._call(self.conn.uid, "FETCH", uid_set(uids), "(UID FLAGS INTERNALDATE BODY.PEEK[])")
        return [Fetched(uid, flags, date, body) for uid, flags, date, body, _ in parse_fetch(data, True)]

    def fetch_flags(self, uids=None, changedsince=None):
        spec = uid_set(uids) if uids else "1:*"
        items = "(UID FLAGS)"
        if changedsince is not None:
            items = f"(UID FLAGS) (CHANGEDSINCE {int(changedsince)})"
        data = self._call(self.conn.uid, "FETCH", spec, items)
        return {uid: flags for uid, flags, _, _, _ in parse_fetch(data, False)}

    def store_flags(self, uids, add, remove):
        if not uids:
            return
        self._writable()
        spec = uid_set(uids)
        if add:
            self._call(self.conn.uid, "STORE", spec, "+FLAGS.SILENT", "(" + " ".join(add) + ")")
        if remove:
            self._call(self.conn.uid, "STORE", spec, "-FLAGS.SILENT", "(" + " ".join(remove) + ")")

    def _copyuid(self):
        resp = self.conn.untagged_responses.pop("COPYUID", None)
        if not resp:
            return None, {}
        m = _COPYUID_RE.search(resp[-1] if isinstance(resp[-1], bytes) else b"")
        if not m:
            return None, {}
        src, dst = expand_set(m.group(2)), expand_set(m.group(3))
        return int(m.group(1)), dict(zip(src, dst))

    def move(self, uids, dest):
        if not uids:
            return None, {}
        self._writable()
        spec = uid_set(uids)
        self.conn.untagged_responses.pop("COPYUID", None)
        if "MOVE" in self.capabilities:
            self._call(self.conn.uid, "MOVE", spec, _quote(dest))
            return self._copyuid()
        if "UIDPLUS" not in self.capabilities:
            raise ServerError("server supports neither MOVE nor UIDPLUS; refusing unsafe move")
        self._call(self.conn.uid, "COPY", spec, _quote(dest))
        result = self._copyuid()
        self.store_flags(uids, ["\\Deleted"], [])
        self.expunge_uids(uids)
        return result

    def expunge_uids(self, uids):
        if not uids:
            return
        if "UIDPLUS" not in self.capabilities:
            raise ServerError("UIDPLUS required for safe expunge")
        self._writable()
        self._call(self.conn.uid, "EXPUNGE", uid_set(uids))

    def append(self, folder, raw, flags, date=None):
        self.conn.untagged_responses.pop("APPENDUID", None)
        when = imaplib.Time2Internaldate((date or datetime.now(timezone.utc)).timestamp())
        flag_str = "(" + " ".join(flags) + ")" if flags else None
        self._call(self.conn.append, _quote(folder), flag_str, when, raw)
        resp = self.conn.untagged_responses.pop("APPENDUID", None)
        if resp and isinstance(resp[-1], bytes):
            parts = resp[-1].split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
        return None

    def create_folder(self, name):
        self._call(self.conn.create, _quote(name))
        try:
            self.conn.subscribe(_quote(name))
        except imaplib.IMAP4.error:
            pass

    def idle_wait(self, timeout):
        """Block in IDLE on the selected folder until the server reports a
        change (True) or timeout passes (False)."""
        if "IDLE" not in self.capabilities:
            import time

            time.sleep(min(timeout, 60))
            return True
        try:
            with self.conn.idle(duration=timeout) as idler:
                for typ, _data in idler:
                    if typ in ("EXISTS", "EXPUNGE", "FETCH", "RECENT", "VANISHED"):
                        return True
        except (imaplib.IMAP4.abort, OSError, socket.timeout) as exc:
            raise OSError(f"IDLE failed: {exc}") from exc
        except imaplib.IMAP4.error as exc:
            raise ServerError(str(exc)) from exc
        return False

    def close(self):
        try:
            self.conn.logout()
        except Exception:
            pass


def connect_from_settings():
    """Connect with the active user's account (mail/account.py)."""
    from .. import account

    cfg = account.cfg()
    return ImapClient(cfg["IMAP_HOST"], cfg["IMAP_PORT"], cfg["LOGIN"], account.password(),
                      verify_tls=cfg["TLS_VERIFY"])
