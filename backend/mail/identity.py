from __future__ import annotations

from .account import cfg


def my_addresses() -> set[str]:
    """The account's address, its aliases and every "send as" address (mail/identities.py)."""
    from .identities import addresses as identity_addresses

    c = cfg()
    addrs = {c["USERNAME"].lower(), *(a.strip().lower() for a in c["ALIASES"])}
    if c["USERNAME"]:
        addrs |= identity_addresses()
    addrs.discard("")
    return addrs


def my_domain() -> str:
    return cfg()["USERNAME"].rpartition("@")[2].lower() or "localhost"
