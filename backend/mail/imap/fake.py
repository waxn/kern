"""In-memory mail server for tests and the offline demo mode."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .base import Fetched, FolderInfo, SelectInfo, ServerError


@dataclass
class _Msg:
    uid: int
    raw: bytes
    flags: set[str]
    date: datetime
    modseq: int


@dataclass
class _Box:
    name: str
    uidvalidity: int
    uidnext: int = 1
    msgs: dict[int, _Msg] = field(default_factory=dict)
    special: str = ""


class FakeMailServer:
    def __init__(self, folders=("INBOX", "Sent", "Drafts", "Junk", "Trash", "Archive"),
                 capabilities=("IMAP4REV1", "UIDPLUS", "MOVE", "CONDSTORE", "IDLE"), uidvalidity_start=1000):
        self.capabilities = set(capabilities)
        self.boxes: dict[str, _Box] = {}
        self._validity = uidvalidity_start
        self._modseq = 1
        self.selected: _Box | None = None
        self.sent: list[tuple[str, list[str], bytes]] = []
        self.changed = threading.Event()
        specials = {"Sent": "\\Sent", "Drafts": "\\Drafts", "Junk": "\\Junk", "Trash": "\\Trash", "Archive": "\\Archive"}
        for name in folders:
            self.create_folder(name)
            self.boxes[name].special = specials.get(name, "")
        self.log: list[tuple] = []

    # -- test helpers ---------------------------------------------------
    def deliver(self, folder: str, raw: bytes, flags=(), date: datetime | None = None) -> int:
        box = self.boxes[folder]
        uid = box.uidnext
        box.uidnext += 1
        self._modseq += 1
        box.msgs[uid] = _Msg(uid, raw, set(flags), date or datetime.now(timezone.utc), self._modseq)
        self.changed.set()
        return uid

    def reset_uidvalidity(self, folder: str) -> None:
        self._validity += 1
        self.boxes[folder].uidvalidity = self._validity

    def flags_of(self, folder: str, uid: int) -> set[str]:
        return self.boxes[folder].msgs[uid].flags

    # -- MailServer -----------------------------------------------------
    def list_folders(self):
        return [FolderInfo(b.name, "/", [b.special] if b.special else []) for b in self.boxes.values()]

    def select(self, name, readonly=True):
        box = self.boxes.get(name)
        if box is None:
            raise ServerError(f"no such folder {name}")
        self.selected = box
        hms = max((m.modseq for m in box.msgs.values()), default=1)
        return SelectInfo(box.uidvalidity, box.uidnext, len(box.msgs), hms)

    def _box(self) -> _Box:
        if self.selected is None:
            raise ServerError("no folder selected")
        return self.selected

    def search_uids(self):
        return sorted(self._box().msgs)

    def fetch_full(self, uids):
        box = self._box()
        self.full_fetches = getattr(self, "full_fetches", 0) + len(uids)
        return [Fetched(u, sorted(box.msgs[u].flags), box.msgs[u].date, box.msgs[u].raw) for u in uids if u in box.msgs]

    def fetch_flags(self, uids=None, changedsince=None):
        box = self._box()
        out = {}
        for uid, m in box.msgs.items():
            if uids is not None and uid not in uids:
                continue
            if changedsince is not None and m.modseq <= changedsince:
                continue
            out[uid] = sorted(m.flags)
        return out

    def store_flags(self, uids, add, remove):
        box = self._box()
        self.log.append(("store", box.name, tuple(uids), tuple(add), tuple(remove)))
        for u in uids:
            if u in box.msgs:
                m = box.msgs[u]
                m.flags |= set(add)
                m.flags -= set(remove)
                self._modseq += 1
                m.modseq = self._modseq

    def move(self, uids, dest):
        src = self._box()
        if "MOVE" not in self.capabilities:
            raise ServerError("MOVE not supported")
        target = self.boxes.get(dest)
        if target is None:
            raise ServerError(f"[TRYCREATE] no such mailbox {dest}")
        mapping = {}
        self.log.append(("move", src.name, tuple(uids), dest))
        for u in uids:
            m = src.msgs.pop(u, None)
            if m is None:
                continue
            new = target.uidnext
            target.uidnext += 1
            self._modseq += 1
            target.msgs[new] = _Msg(new, m.raw, set(m.flags), m.date, self._modseq)
            mapping[u] = new
        if "UIDPLUS" in self.capabilities:
            return target.uidvalidity, mapping
        return None, {}

    def expunge_uids(self, uids):
        box = self._box()
        self.log.append(("expunge", box.name, tuple(uids)))
        for u in uids:
            if u in box.msgs and "\\Deleted" in box.msgs[u].flags:
                del box.msgs[u]

    def append(self, folder, raw, flags, date=None):
        if folder not in self.boxes:
            raise ServerError(f"[TRYCREATE] no such mailbox {folder}")
        uid = self.deliver(folder, raw, flags, date)
        self.log.append(("append", folder, uid))
        return uid if "UIDPLUS" in self.capabilities else None

    def create_folder(self, name):
        if name in self.boxes:
            raise ServerError("folder already exists")
        self._validity += 1
        self.boxes[name] = _Box(name, self._validity)

    def idle_wait(self, timeout):
        hit = self.changed.wait(timeout)
        self.changed.clear()
        return hit

    def close(self):
        pass


class FakeSender:
    def __init__(self, server: FakeMailServer | None = None):
        self.sent: list[tuple[str, list[str], bytes]] = []
        self.server = server

    def send(self, envelope_from, recipients, raw):
        self.sent.append((envelope_from, list(recipients), raw))
        return {}
