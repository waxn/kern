"""Image proxy for "load images".

SECURITY (review carefully):
* Only URLs signed by the sanitizer (HMAC with SECRET_KEY) are fetched, so
  neither a hostile email nor another site can make your server fetch
  arbitrary URLs. The endpoint also requires your session.
* SSRF guard: the hostname is resolved once, every resolved address must be
  public (no loopback, private, link-local, CGNAT, multicast or reserved
  ranges), and the connection goes to that vetted IP (no DNS-rebinding
  window). Redirects are re-validated the same way.
* The upstream request carries no cookies, no Referer and a generic
  User-Agent. Your browser never contacts the sender's server, so trackers
  only see your server's IP, once.
* Only raster image types are passed through, size-capped, with nosniff and
  a sandbox CSP on the response.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

from django.conf import settings

ALLOWED_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/avif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
}
MAX_REDIRECTS = 3
TIMEOUT = 8
CGNAT = ipaddress.ip_network("100.64.0.0/10")


class ProxyError(Exception):
    pass


def _key() -> bytes:
    return hashlib.sha256(b"manifest-imgproxy:" + settings.SECRET_KEY.encode()).digest()


def sign(url: str) -> str:
    mac = hmac.new(_key(), url.encode("utf-8"), hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def verify(url: str, sig: str) -> bool:
    return hmac.compare_digest(sign(url), sig or "")


def signed_path(url: str) -> str:
    return f"/api/mail/img?u={quote(url, safe='')}&s={sign(url)}"


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.version == 4 and addr in CGNAT:
        return False
    return bool(addr.is_global) and not addr.is_multicast and not addr.is_reserved


def resolve_public(host: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProxyError(f"DNS failed for {host}") from exc
    ips = [info[4][0] for info in infos]
    if not ips:
        raise ProxyError("no address")
    for ip in ips:
        if not is_public_ip(ip):
            raise ProxyError(f"refusing non-public address for {host}")
    return ips[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, **kw):
        super().__init__(host, port, timeout=TIMEOUT, context=ssl.create_default_context(), **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, ip, port, **kw):
        super().__init__(host, port, timeout=TIMEOUT, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


@dataclass
class Fetched:
    content_type: str
    body: bytes


def fetch(url: str, *, resolver=resolve_public) -> Fetched:
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ProxyError("bad url")
        if parts.username or parts.password:
            raise ProxyError("credentials in url")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = resolver(parts.hostname, port)
        cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        conn = cls(parts.hostname, ip, port)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        try:
            conn.request("GET", path, headers={
                "User-Agent": "Mozilla/5.0 (compatible; image-proxy)",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,image/*;q=0.8",
                "Accept-Encoding": "identity",
            })
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise ProxyError("redirect without location")
                url = urljoin(url, loc)
                continue
            if resp.status != 200:
                raise ProxyError(f"upstream status {resp.status}")
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in ALLOWED_TYPES:
                raise ProxyError(f"type {ctype!r} not allowed")
            limit = settings.IMAGE_PROXY_MAX_BYTES
            declared = resp.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise ProxyError("too large")
            body = resp.read(limit + 1)
            if len(body) > limit:
                raise ProxyError("too large")
            return Fetched(ctype, body)
        except (OSError, http.client.HTTPException) as exc:
            raise ProxyError(f"fetch failed: {exc.__class__.__name__}") from exc
        finally:
            conn.close()
    raise ProxyError("too many redirects")
