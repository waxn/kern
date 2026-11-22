"""How people are named in lists: one rule for the web app, the Android app and notifications."""

from __future__ import annotations

import re


def display_name(p: dict) -> str:
    """The name they gave, else the part of the address before the @."""
    if not p:
        return ""
    name = (p.get("name") or "").strip()
    if name:
        return name
    addr = p.get("addr") or ""
    return addr.split("@")[0] if addr else ""


def first_name(p: dict) -> str:
    n = display_name(p)
    return (re.split(r"[\s,]+", n)[0] or n) if n else ""


def participants_label(participants: list[dict], me: set[str]) -> str:
    """"Alice", "Alice, Bob", "Alice … Carol" or "To: Dana" for a conversation you started."""
    everyone = participants or []
    mine = {a.lower() for a in me}
    senders = [p for p in everyone if not p.get("to") and (p.get("addr") or "").lower() not in mine]
    if not senders:
        to = [p for p in everyone if p.get("to")]
        if to:
            return "To: " + ", ".join(first_name(p) for p in to[:3]) + ("…" if len(to) > 3 else "")
    people = senders or [p for p in everyone if not p.get("to")]
    if not people:
        return "(no sender)"
    if len(people) == 1:
        return display_name(people[0])
    a, b = people[0], people[-1]
    short = first_name(a) != first_name(b)  # full names when first names alone would be ambiguous
    na, nb = (first_name(a), first_name(b)) if short else (display_name(a), display_name(b))
    return f"{na}, {nb}" if len(people) == 2 else f"{na} … {nb}"
