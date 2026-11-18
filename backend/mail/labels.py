"""Labels are stored on the server as IMAP keywords, so they survive a
database rebuild and travel with the message.

Keyword format: "$ML_" + name for simple ASCII names, otherwise
"$MLX_" + base32(utf-8 name). IMAP keywords are atoms: no spaces, quotes,
parentheses or non-ASCII.
"""

from __future__ import annotations

import base64
import re

from .models import Label

PREFIX = "$ML_"
PREFIX_X = "$MLX_"
_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")


def keyword_for(name: str) -> str:
    if _SAFE.match(name):
        return PREFIX + name
    enc = base64.b32encode(name.encode("utf-8")).decode().rstrip("=")
    return PREFIX_X + enc


def name_for(keyword: str) -> str | None:
    if keyword.startswith(PREFIX_X):
        raw = keyword[len(PREFIX_X):]
        try:
            return base64.b32decode(raw + "=" * (-len(raw) % 8)).decode("utf-8")
        except Exception:
            return None
    if keyword.startswith(PREFIX):
        return keyword[len(PREFIX):] or None
    return None


def get_or_create(name: str) -> Label:
    name = name.strip()[:128]
    label, _ = Label.objects.get_or_create(name=name, defaults={"keyword": keyword_for(name)})
    return label


def labels_from_keywords(keywords: list[str]) -> list[Label]:
    out = []
    for kw in keywords:
        name = name_for(kw)
        if name:
            label = Label.objects.filter(keyword=kw).first() or get_or_create(name)
            out.append(label)
    return out
