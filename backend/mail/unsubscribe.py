"""List-Unsubscribe handling, including RFC 8058 one-click.

SECURITY (review): a one-click unsubscribe makes your *server* send a POST
to a URL taken from an email. So it only happens when
  * you clicked Unsubscribe and confirmed,
  * the message carries `List-Unsubscribe-Post: List-Unsubscribe=One-Click`,
  * the URL is https, and
  * your provider verified a DKIM signature on the message (RFC 8058 requires
    the headers to be DKIM-covered; we can't check coverage per header, so
    we require a passing signature from the sender's domain).
The request goes through the image proxy's SSRF guard (public addresses
only, pinned IP), carries only the fixed body `List-Unsubscribe=One-Click`,
no cookies, and doesn't follow redirects. Otherwise the user gets the link
(or mailto) to use themselves.
"""

from __future__ import annotations

import http.client
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .imgproxy import ProxyError, _PinnedHTTPSConnection, resolve_public
from .risk.domains import org_domain

_ANGLE = re.compile(r"<([^>]+)>")


@dataclass
class Options:
    https: str | None
    mailto: str | None
    one_click: bool


def options(message) -> Options | None:
    raw = (message.headers or {}).get("list-unsubscribe", "")
    if not raw:
        return None
    https = mailto = None
    for target in _ANGLE.findall(raw):
        t = target.strip()
        if t.lower().startswith("https://") and not https:
            https = t
        elif t.lower().startswith("mailto:") and not mailto:
            mailto = t
    if not (https or mailto):
        return None
    post = (message.headers or {}).get("list-unsubscribe-post", "")
    one_click = bool(https) and "list-unsubscribe=one-click" in post.replace(" ", "").lower() and _dkim_ok(message)
    return Options(https=https, mailto=mailto, one_click=one_click)


def _dkim_ok(message) -> bool:
    auth = message.auth_results or {}
    if not auth.get("trusted"):
        return False
    sender_org = org_domain(message.from_addr.rpartition("@")[2])
    for d in auth.get("dkim", []):
        if d.get("result") == "pass" and d.get("domain") and org_domain(d["domain"]) == sender_org:
            return True
    return False


def one_click(url: str, *, resolver=resolve_public) -> int:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ProxyError("bad url")
    port = parts.port or 443
    ip = resolver(parts.hostname, port)
    conn = _PinnedHTTPSConnection(parts.hostname, ip, port)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    try:
        conn.request("POST", path, body=b"List-Unsubscribe=One-Click", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (compatible; one-click-unsubscribe)",
        })
        resp = conn.getresponse()
        resp.read(65536)
        if not 200 <= resp.status < 300:
            raise ProxyError(f"server answered {resp.status}")
        return resp.status
    except (OSError, http.client.HTTPException) as exc:
        raise ProxyError(f"request failed: {exc.__class__.__name__}") from exc
    finally:
        conn.close()
