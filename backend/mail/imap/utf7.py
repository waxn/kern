"""IMAP "modified UTF-7" mailbox names (RFC 3501 section 5.1.3)."""

from __future__ import annotations

import base64


def decode(name: str) -> str:
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:
            out.append(name[i:])
            break
        chunk = name[i + 1:end]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            except (ValueError, UnicodeDecodeError):
                out.append(name[i:end + 1])
        i = end + 1
    return "".join(out)


def encode(name: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            raw = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)
