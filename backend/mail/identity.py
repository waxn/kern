from __future__ import annotations

from .account import cfg


def my_addresses() -> set[str]:
    c = cfg()
    addrs = {c["USERNAME"].lower(), *(a.strip().lower() for a in c["ALIASES"])}
    addrs.discard("")
    return addrs


def my_domain() -> str:
    return cfg()["USERNAME"].rpartition("@")[2].lower() or "localhost"
