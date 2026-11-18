"""Interface between the sync engine and a mail server.

The engine only talks to this interface, so tests and the demo mode use an
in-memory FakeMailServer (mail/imap/fake.py) and production uses imaplib
(mail/imap/client.py). The web process never talks to the mail server;
only the sync worker does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ServerError(Exception):
    pass


class UidValidityChanged(ServerError):
    pass


@dataclass
class FolderInfo:
    name: str
    delimiter: str
    flags: list[str]

    @property
    def selectable(self) -> bool:
        return not any(f.lower() == "\\noselect" or f.lower() == "\\nonexistent" for f in self.flags)


@dataclass
class SelectInfo:
    uidvalidity: int
    uidnext: int | None
    exists: int
    highestmodseq: int | None = None


@dataclass
class Fetched:
    uid: int
    flags: list[str]
    internal_date: datetime | None
    raw: bytes


class MailServer(Protocol):
    capabilities: set[str]

    def list_folders(self) -> list[FolderInfo]: ...
    def select(self, name: str, readonly: bool = True) -> SelectInfo: ...
    def search_uids(self) -> list[int]: ...
    def fetch_full(self, uids: list[int]) -> list[Fetched]: ...
    def fetch_flags(self, uids: list[int] | None = None, changedsince: int | None = None) -> dict[int, list[str]]: ...
    def store_flags(self, uids: list[int], add: list[str], remove: list[str]) -> None: ...
    def move(self, uids: list[int], dest: str) -> tuple[int | None, dict[int, int]]:
        """Returns (dest uidvalidity, {old uid: new uid}) from COPYUID, or (None, {})."""
        ...
    def expunge_uids(self, uids: list[int]) -> None: ...
    def append(self, folder: str, raw: bytes, flags: list[str], date: datetime | None = None) -> int | None: ...
    def create_folder(self, name: str) -> None: ...
    def idle_wait(self, timeout: float) -> bool: ...
    def close(self) -> None: ...


class MailSender(Protocol):
    def send(self, envelope_from: str, recipients: list[str], raw: bytes) -> dict: ...


ROLE_FLAGS = {
    "\\sent": "sent",
    "\\drafts": "drafts",
    "\\junk": "junk",
    "\\trash": "trash",
    "\\archive": "archive",
    "\\all": "all",
}
ROLE_NAMES = {
    "sent": "sent", "sent items": "sent", "sent messages": "sent", "sent mail": "sent",
    "drafts": "drafts", "draft": "drafts",
    "junk": "junk", "spam": "junk", "junk e-mail": "junk", "junk email": "junk", "bulk mail": "junk",
    "trash": "trash", "deleted items": "trash", "deleted messages": "trash", "bin": "trash", "deleted": "trash",
    "archive": "archive", "archives": "archive",
    "snoozed": "snoozed",
}


def detect_role(info: FolderInfo) -> str:
    if info.name.upper() == "INBOX":
        return "inbox"
    for f in info.flags:
        role = ROLE_FLAGS.get(f.lower())
        if role:
            return role
    leaf = info.name.split(info.delimiter)[-1] if info.delimiter else info.name
    return ROLE_NAMES.get(leaf.strip().lower(), "")
