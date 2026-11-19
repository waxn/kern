"""Which remote addresses Kern may connect to on a user's behalf (push mirrors, webhooks).

SECURITY: users type in URLs and the server connects to them. Without a check, any Kern user
could make the server talk to machines on its private network (the database, a router's admin
page, cloud metadata...). Every address the host resolves to must be public unless the
administrator turned on "allow_local_git_remotes" (Settings -> Server). Like ``mail/hosts.py``,
the check is made when the URL is saved and again right before each connection. Mirrors also
pin git to the checked addresses (``http.curloptResolve``), so a DNS answer that changes in
between cannot redirect the push; webhooks have a small remaining rebinding window (documented).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class RemoteNotAllowed(ValueError):
    pass


def local_allowed() -> bool:
    try:
        from accounts import site

        return bool(site.get_all().get("allow_local_git_remotes"))
    except Exception:
        return False


def _is_public(ip) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise RemoteNotAllowed(f"Couldn't find {host}. Check the spelling.") from None
    out = []
    for info in infos:
        a = info[4][0].split("%")[0]
        if a not in out:
            out.append(a)
    if not out:
        raise RemoteNotAllowed(f"Couldn't find {host}.")
    return out


def check_url(url: str, *, http: str = "yes") -> dict:
    """Validate ``url`` and return {url, scheme, host, port, addrs}.

    ``http``: "yes" allows http and https; "local" allows https, and http only to non-public
    addresses when local remotes are allowed (so a token never crosses the internet unencrypted);
    "no" allows https only."""
    url = (url or "").strip()
    if not url or len(url) > 500 or any(c.isspace() or ord(c) < 32 for c in url):
        raise RemoteNotAllowed("Enter a full URL like https://example.com/...")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise RemoteNotAllowed("That URL isn't valid.") from None
    if u.scheme not in ("http", "https") or not u.hostname:
        raise RemoteNotAllowed("The URL must start with https://" + (" or http://" if http == "yes" else ""))
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise RemoteNotAllowed("Don't put a username or password in the URL; enter them in the separate fields.")
    if u.scheme == "http" and http == "no":
        raise RemoteNotAllowed("Only https:// URLs are allowed.")
    port = port or (443 if u.scheme == "https" else 80)
    if not (0 < port < 65536):
        raise RemoteNotAllowed("That port isn't valid.")
    addrs = resolve(u.hostname, port)
    public = all(_is_public(ipaddress.ip_address(a)) for a in addrs)
    if not public and not local_allowed():
        raise RemoteNotAllowed(f"{u.hostname} is on a private network. An administrator can allow local git "
                               "remotes and webhooks in Settings → Server.")
    if u.scheme == "http" and http == "local" and public:
        raise RemoteNotAllowed("Only https:// URLs are allowed for public servers.")
    return {"url": url, "scheme": u.scheme, "host": u.hostname, "port": port, "addrs": addrs}
