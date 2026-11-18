"""A tiny IMAP4rev1 server speaking the real wire protocol, for tests.

It exists so the production client (mail/imap/client.py, built on imaplib)
can be exercised end to end without Docker: literals, tagged/untagged
responses, response codes (UIDVALIDITY, COPYUID, APPENDUID, HIGHESTMODSEQ),
UID commands and IDLE. Mail lives in a FakeMailServer. Plain TCP only.
"""

from __future__ import annotations

import re
import socket
import socketserver
import threading
from datetime import datetime, timezone

from ..imap import utf7
from ..imap.fake import FakeMailServer

CAPS = "IMAP4rev1 UIDPLUS MOVE IDLE CONDSTORE ENABLE"


def _uids(spec: str, existing: list[int]) -> list[int]:
    out = []
    top = max(existing) if existing else 0
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            lo = int(a)
            hi = top if b == "*" else int(b)
            lo, hi = min(lo, hi), max(lo, hi)
            out += [u for u in existing if lo <= u <= hi]
        elif part == "*":
            out += existing[-1:]
        else:
            out.append(int(part))
    return [u for u in dict.fromkeys(out) if u in existing]


def _set(uids: list[int]) -> str:
    return ",".join(str(u) for u in uids)


def _astring(tokens: list[str], i: int) -> str:
    t = tokens[i]
    return t[1:-1].replace('\\"', '"').replace("\\\\", "\\") if t.startswith('"') else t


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\([^)]*\)|\S+')


class _Handler(socketserver.StreamRequestHandler):
    server: "IMAPTestServer"

    def send(self, line: str | bytes) -> None:
        data = line if isinstance(line, bytes) else line.encode()
        self.wfile.write(data + b"\r\n")
        self.wfile.flush()

    def read_line(self) -> bytes | None:
        line = self.rfile.readline()
        return line or None

    def handle(self):
        mail: FakeMailServer = self.server.mail
        selected = None
        self.send(f"* OK [CAPABILITY {CAPS}] test server ready")
        while True:
            raw = self.read_line()
            if raw is None:
                return
            line = raw.rstrip(b"\r\n")
            literal = None
            m = re.search(rb"\{(\d+)\}$", line)
            if m:  # client sends a literal (APPEND)
                self.send("+ go ahead")
                literal = self.rfile.read(int(m.group(1)))
                rest = self.read_line() or b""
                line = line[: m.start()].rstrip() + rest.rstrip(b"\r\n")
            text = line.decode("utf-8", "replace")
            parts = text.split(" ", 2)
            tag = parts[0]
            cmd = parts[1].upper() if len(parts) > 1 else ""
            args = parts[2] if len(parts) > 2 else ""
            if cmd == "IDLE":  # outside the lock: it blocks until DONE
                self.send("+ idling")
                self.server.idlers.append(self)
                try:
                    while True:
                        nxt = self.read_line()
                        if nxt is None or nxt.strip().upper() == b"DONE":
                            break
                finally:
                    self.server.idlers.remove(self)
                self.send(f"{tag} OK IDLE terminated")
                continue
            with self.server.lock:
                try:
                    if cmd == "UID":
                        sub, _, rest = args.partition(" ")
                        selected = self.uid(tag, sub.upper(), rest, mail, selected)
                        continue
                    if cmd == "CAPABILITY":
                        self.send(f"* CAPABILITY {CAPS}")
                    elif cmd == "LOGIN":
                        toks = _TOKEN.findall(args)
                        user, pw = _astring(toks, 0), _astring(toks, 1)
                        if (user, pw) != (self.server.user, self.server.password):
                            self.send(f"{tag} NO [AUTHENTICATIONFAILED] invalid credentials")
                            continue
                    elif cmd == "ENABLE":
                        self.send("* ENABLED CONDSTORE")
                    elif cmd == "LIST":
                        for name, box in mail.boxes.items():
                            flags = box.special or "\\HasNoChildren"
                            self.send(f'* LIST ({flags}) "/" "{utf7.encode(name)}"')
                    elif cmd in ("SELECT", "EXAMINE"):
                        name = utf7.decode(_astring(_TOKEN.findall(args), 0))
                        info = mail.select(name)
                        selected = name
                        self.send(f"* {info.exists} EXISTS")
                        self.send("* FLAGS (\\Seen \\Flagged \\Answered \\Deleted \\Draft)")
                        self.send(f"* OK [UIDVALIDITY {info.uidvalidity}] ok")
                        self.send(f"* OK [UIDNEXT {info.uidnext}] ok")
                        self.send(f"* OK [HIGHESTMODSEQ {info.highestmodseq}] ok")
                        mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                        self.send(f"{tag} OK [{mode}] done")
                        continue
                    elif cmd == "CREATE":
                        mail.create_folder(utf7.decode(_astring(_TOKEN.findall(args), 0)))
                    elif cmd == "SUBSCRIBE":
                        pass
                    elif cmd == "APPEND":
                        toks = _TOKEN.findall(args)
                        name = utf7.decode(_astring(toks, 0))
                        flags = []
                        for t in toks[1:]:
                            if t.startswith("("):
                                flags = t[1:-1].split()
                        uid = mail.deliver(name, literal or b"", flags)
                        self.send(f"{tag} OK [APPENDUID {mail.boxes[name].uidvalidity} {uid}] appended")
                        continue
                    elif cmd == "NOOP":
                        pass
                    elif cmd == "LOGOUT":
                        self.send("* BYE see you")
                        self.send(f"{tag} OK bye")
                        return
                    else:
                        self.send(f"{tag} BAD unknown command {cmd}")
                        continue
                    self.send(f"{tag} OK {cmd} completed")
                except Exception as exc:  # noqa: BLE001 - report as NO like a server would
                    self.send(f"{tag} NO {exc}")

    def uid(self, tag, sub, rest, mail: FakeMailServer, selected):
        box = mail.boxes[selected]
        existing = sorted(box.msgs)
        if sub == "SEARCH":
            self.send("* SEARCH " + " ".join(str(u) for u in existing))
        elif sub == "FETCH":
            spec, _, items = rest.partition(" ")
            changedsince = None
            m = re.search(r"\(CHANGEDSINCE (\d+)\)", items)
            if m:
                changedsince = int(m.group(1))
            for i, uid in enumerate(_uids(spec, existing), 1):
                msg = box.msgs[uid]
                if changedsince is not None and msg.modseq <= changedsince:
                    continue
                flags = " ".join(sorted(msg.flags))
                head = f"* {i} FETCH (UID {uid} FLAGS ({flags}) MODSEQ ({msg.modseq})"
                if "INTERNALDATE" in items.upper():
                    head += ' INTERNALDATE "' + msg.date.strftime("%d-%b-%Y %H:%M:%S +0000") + '"'
                if "BODY" in items.upper():
                    self.wfile.write(f"{head} BODY[] {{{len(msg.raw)}}}\r\n".encode() + msg.raw + b")\r\n")
                else:
                    self.send(head + ")")
        elif sub == "STORE":
            spec, op, flags = rest.split(" ", 2)
            fl = flags.strip("()").split()
            uids = _uids(spec, existing)
            mail.select(selected)
            mail.store_flags(uids, fl if op.startswith("+") else [], fl if op.startswith("-") else [])
        elif sub in ("MOVE", "COPY"):
            spec, _, dest = rest.partition(" ")
            dest = utf7.decode(dest.strip('"'))
            uids = _uids(spec, existing)
            mail.select(selected)
            if sub == "COPY":
                new = [mail.deliver(dest, box.msgs[u].raw, box.msgs[u].flags) for u in uids]
                validity = mail.boxes[dest].uidvalidity
            else:
                validity, mapping = mail.move(uids, dest)
                new = [mapping[u] for u in uids]
            self.send(f"* OK [COPYUID {validity} {_set(uids)} {_set(new)}] copied")
            if sub == "MOVE":
                for _ in uids:
                    self.send("* 1 EXPUNGE")
        elif sub == "EXPUNGE":
            uids = _uids(rest, existing)
            mail.select(selected)
            mail.expunge_uids(uids)
        else:
            self.send(f"{tag} BAD unknown UID command {sub}")
            return selected
        self.send(f"{tag} OK UID {sub} completed")
        return selected


class IMAPTestServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mail: FakeMailServer, user="me@manifest.test", password="secret"):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mail = mail
        self.user = user
        self.password = password
        self.lock = threading.RLock()
        self.idlers: list[_Handler] = []

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self) -> "IMAPTestServer":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def notify_new(self, folder: str = "INBOX") -> None:
        """Tell IDLE-ing clients that mail arrived."""
        count = len(self.mail.boxes[folder].msgs)
        for h in list(self.idlers):
            try:
                h.send(f"* {count} EXISTS")
            except OSError:
                pass

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


__all__ = ["IMAPTestServer", "datetime", "timezone", "socket"]
