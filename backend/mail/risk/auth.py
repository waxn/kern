"""Parsing Authentication-Results (RFC 8601) headers.

SECURITY (review): anyone can put an Authentication-Results header in a
message they send. We only trust the block of Authentication-Results headers
written by YOUR provider: those whose authserv-id equals MAIL_AUTHSERV_ID,
taken from the top of the header block and only until the first Received
header below them (headers added before the mail reached your provider
sit below that line and are ignored).
"""

from __future__ import annotations

import re

from ..parsing import decode_header_value

_COMMENT = re.compile(r"\([^()]*\)")
_RES = re.compile(r"^\s*([a-z0-9_-]+)(?:\s*/\s*\d+)?\s*=\s*([a-z]+)", re.IGNORECASE)
_PROP = re.compile(r"\b([a-z]+)\.([a-z0-9_-]+)\s*=\s*(\"[^\"]*\"|[^\s;]+)", re.IGNORECASE)


def _strip_comments(value: str) -> str:
    for _ in range(5):
        new = _COMMENT.sub(" ", value)
        if new == value:
            break
        value = new
    return value


def authserv_id(value: str) -> str:
    first = _strip_comments(value).split(";", 1)[0].strip()
    return first.split()[0].lower() if first else ""


def trusted_headers(header_items: list[tuple[str, str]], expected_id: str) -> list[str]:
    expected_id = (expected_id or "").lower()
    found: list[str] = []
    started = False
    for name, value in header_items:
        lname = name.lower()
        if lname == "authentication-results":
            v = decode_header_value(value)
            if authserv_id(v) == expected_id:
                found.append(v)
                started = True
                continue
            if started:
                break
        elif lname == "received" and started:
            break
    return found


def parse(values: list[str]) -> dict:
    """Returns {"trusted": bool, "spf": str, "dkim": [{"result","domain"}],
    "dmarc": str, "dmarc_from": str, "spf_domain": str, "arc": str}."""
    out = {"trusted": bool(values), "spf": "", "spf_domain": "", "dkim": [], "dmarc": "",
           "dmarc_from": "", "arc": ""}
    for value in values:
        segments = _strip_comments(value).split(";")[1:]
        for seg in segments:
            m = _RES.match(seg)
            if not m:
                continue
            method, result = m.group(1).lower(), m.group(2).lower()
            props = {f"{a.lower()}.{b.lower()}": c.strip('"').lower() for a, b, c in _PROP.findall(seg)}
            if method == "spf" and not out["spf"]:
                out["spf"] = result
                mf = props.get("smtp.mailfrom", "")
                out["spf_domain"] = mf.rpartition("@")[2]
            elif method == "dkim":
                out["dkim"].append({"result": result, "domain": props.get("header.d") or props.get("header.i", "").lstrip("@").rpartition("@")[2]})
            elif method == "dmarc" and not out["dmarc"]:
                out["dmarc"] = result
                out["dmarc_from"] = props.get("header.from", "")
            elif method == "arc" and not out["arc"]:
                out["arc"] = result
    return out
