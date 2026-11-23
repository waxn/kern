"""Server-side preferences (shared by every device you use).

Per-device choices like theme and density stay in the browser; these are the
ones that change what Manifest does: your name and signature on outgoing
mail, how long Undo send waits, and reading behaviour.
"""

from __future__ import annotations

from django.conf import settings

from .models import Preferences

DEFAULTS = {
    "from_name": "",            # empty: use MAIL_FROM_NAME from .env
    "signature": "",            # plain text
    "signature_on_replies": True,
    "undo_seconds": None,       # None: use SEND_UNDO_SECONDS from .env
    "after_action": "next",     # after archive/trash/...: "next" conversation or back to "list"
    "load_images": False,       # load remote images in every message (through the image proxy)
    "mark_read": "open",        # "open" (immediately), "delay" (after 2s), "manual"
}

LIMITS = {
    "from_name": 200,
    "signature": 4000,
}


def get() -> dict:
    row = Preferences.objects.filter(pk=1).first()
    data = dict(DEFAULTS)
    if row:
        data.update({k: v for k, v in row.data.items() if k in DEFAULTS})
    return data


def update(changes: dict) -> dict:
    data = get()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown preference: {key}")
        if key in ("from_name", "signature"):
            value = str(value or "").replace("\r\n", "\n")[: LIMITS[key]]
            if key == "from_name":
                value = " ".join(value.split())
        elif key in ("signature_on_replies", "load_images"):
            value = bool(value)
        elif key == "undo_seconds":
            value = None if value in (None, "") else max(0, min(60, int(value)))
        elif key == "after_action":
            if value not in ("next", "list"):
                raise ValueError("after_action must be 'next' or 'list'")
        elif key == "mark_read":
            if value not in ("open", "delay", "manual"):
                raise ValueError("mark_read must be 'open', 'delay' or 'manual'")
        data[key] = value
    Preferences.objects.update_or_create(pk=1, defaults={"data": data})
    return data


def from_name() -> str:
    from .account import cfg

    return get()["from_name"] or cfg()["FROM_NAME"]


def undo_seconds() -> int:
    v = get()["undo_seconds"]
    from .account import cfg

    return cfg()["SEND_UNDO_SECONDS"] if v is None else int(v)
