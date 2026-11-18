"""Domain helpers: registrable ("organizational") domain, homoglyph skeletons
and edit distance for lookalike detection. Offline only: the Public Suffix
List ships inside the publicsuffixlist package."""

from __future__ import annotations

import unicodedata
from functools import lru_cache

from publicsuffixlist import PublicSuffixList

_psl = PublicSuffixList()

CONFUSABLES = str.maketrans({
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "l", "ј": "j", "ѕ": "s", "ԁ": "d",
    "ɡ": "g", "ӏ": "l", "ո": "n", "ս": "u",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "l", "κ": "k", "ν": "v", "ο": "o", "ρ": "p",
    "τ": "t", "υ": "u", "χ": "x",
    # Digits / ASCII lookalikes
    "0": "o", "1": "l", "3": "e", "5": "s", "i": "l", "|": "l", "!": "l",
})
MULTI = (("rn", "m"), ("vv", "w"), ("cl", "d"), ("nn", "m"))


def to_ascii(domain: str) -> str:
    try:
        return domain.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return domain


def to_unicode(domain: str) -> str:
    try:
        return domain.encode("ascii").decode("idna") if "xn--" in domain else domain
    except (UnicodeError, ValueError):
        return domain


@lru_cache(maxsize=4096)
def org_domain(domain: str) -> str:
    domain = (domain or "").strip(".").lower()
    if not domain:
        return ""
    try:
        priv = _psl.privatesuffix(to_unicode(domain))
    except Exception:
        priv = None
    if priv:
        return priv
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def org_label(domain: str) -> str:
    """'mail.paypal.co.uk' -> 'paypal'."""
    org = org_domain(domain)
    try:
        suffix = _psl.publicsuffix(org) or ""
    except Exception:
        suffix = ""
    if suffix and org.endswith("." + suffix):
        return org[: -(len(suffix) + 1)]
    return org.split(".")[0]


@lru_cache(maxsize=8192)
def skeleton(s: str) -> str:
    s = unicodedata.normalize("NFKD", to_unicode(s).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.translate(CONFUSABLES)
    for a, b in MULTI:
        s = s.replace(a, b)
    return s.replace("-", "").replace("_", "")


def distance(a: str, b: str, limit: int = 3) -> int:
    """Damerau-Levenshtein (optimal string alignment), capped at limit+1."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2 = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def looks_like(candidate: str, target: str, same_name_counts: bool = True) -> bool:
    """Is domain `candidate` a lookalike of domain `target` (but not it)?

    same_name_counts: treat 'paypal.co' as a lookalike of 'paypal.com'. On for
    brands (whose real domains are listed), off for your contacts (a company
    may legitimately use both company.se and company.com)."""
    if not candidate or not target:
        return False
    if org_domain(candidate) == org_domain(target):
        return False
    a, b = org_label(candidate), org_label(target)
    if len(b) < 4:
        return False
    if a == b:
        # Same name under a different suffix: paypal.co vs paypal.com
        return same_name_counts
    if skeleton(a) == skeleton(b):
        return True
    limit = 2 if len(b) >= 10 else 1
    return len(b) >= 5 and distance(a, b, limit) <= limit


def contains_token(domain: str, token: str) -> bool:
    """'paypal' in 'paypal-secure.com' / 'paypal.com.evil.net' as a whole token."""
    import re

    return token in re.split(r"[.\-_]", to_unicode(domain).lower())
