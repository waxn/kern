"""Which mail servers a user may connect to.

SECURITY: users type in an IMAP/SMTP host, and the server connects to it.
Without a check, any Kern user could make the server talk to machines on its
private network (the database, a router's admin page...). Hosts must resolve
only to public addresses unless the administrator allows local mail servers
(Settings → Server, "allow_local_mail").
"""
from __future__ import annotations

import ipaddress
import socket


class HostNotAllowed(ValueError):
    pass


def local_allowed() -> bool:
    try:
        from accounts import site

        return bool(site.get_all().get("allow_local_mail"))
    except Exception:
        return False


def check(host: str, port: int) -> None:
    host = (host or "").strip()
    if not host or len(host) > 253 or any(c.isspace() for c in host):
        raise HostNotAllowed("Enter a server name like imap.example.com.")
    if not (0 < int(port) < 65536):
        raise HostNotAllowed("That port isn't valid.")
    if local_allowed():
        return
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HostNotAllowed(f"Couldn't find {host}. Check the spelling.") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise HostNotAllowed(f"{host} is on a private network. An administrator can allow local mail servers "
                                 "in Settings → Server.")
