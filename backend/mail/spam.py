"""Block list and the shared-provider guard."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .models import BlockKind, BlockRule
from .risk.domains import org_domain


class BlockError(ValueError):
    pass


@lru_cache(maxsize=1)
def shared_providers() -> frozenset[str]:
    path = Path(__file__).parent / "data" / "shared_providers.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#"))


def is_shared_provider(domain: str) -> bool:
    domain = domain.lower().strip(".")
    providers = shared_providers()
    if domain in providers or org_domain(domain) in providers:
        return True
    return any(domain.endswith("." + p) for p in providers)


def domain_of(addr: str) -> str:
    return addr.rpartition("@")[2].lower()


def add_block(kind: str, value: str, note: str = "") -> BlockRule:
    value = value.strip().lower()
    if kind == BlockKind.ADDRESS:
        if "@" not in value or value.startswith("@"):
            raise BlockError("Not an email address.")
    elif kind == BlockKind.DOMAIN:
        value = value.lstrip("@")
        if "." not in value or "@" in value:
            raise BlockError("Not a domain.")
        if is_shared_provider(value):
            raise BlockError(
                f"{value} is a shared email provider used by many people. "
                "Block the single address instead."
            )
    else:
        raise BlockError("Unknown block type.")
    rule, _ = BlockRule.objects.get_or_create(kind=kind, value=value, defaults={"note": note[:500]})
    return rule


def matching_rule(addr: str) -> BlockRule | None:
    addr = (addr or "").lower()
    if not addr:
        return None
    rule = BlockRule.objects.filter(kind=BlockKind.ADDRESS, value=addr).first()
    if rule:
        return rule
    dom = domain_of(addr)
    candidates = set()
    parts = dom.split(".")
    for i in range(len(parts) - 1):
        candidates.add(".".join(parts[i:]))
    return BlockRule.objects.filter(kind=BlockKind.DOMAIN, value__in=candidates).order_by("-value").first()


def remove_blocks_for(addr: str) -> list[str]:
    """'Not spam': remove the address rule and any domain rule covering it."""
    removed = []
    while True:
        rule = matching_rule(addr)
        if not rule:
            break
        removed.append(f"{rule.kind}:{rule.value}")
        rule.delete()
    return removed
