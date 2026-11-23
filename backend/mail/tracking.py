"""Live package tracking: the carrier's real status, scans and a map, from a tracking service.

Shipping emails only say what the shop knew when it wrote them, so a package delivered without a
"delivered" email would stay "on the way" forever. With live tracking on (Settings → Mail →
Package tracking) the mail worker asks a tracking service about each package every so often and
updates its status, expected day, latest scans and, for the map, where those scans were
(mail/geo.py).

The services (mail/trackers/):

* ``parcels``      Parcels (parcelsapp.com), API key; free for 300 packages a month.
* ``trackingmore`` TrackingMore (trackingmore.com), API key; credits per package.
* ``scraper``      Universal Parcel Scraper (Peek's open-source engine), built into Kern's image:
                   asks each carrier's own site, no account or key. Or point Kern at one you run
                   yourself (its HTTP server, ``POST /v1/track``).

Each returns the same normalized ``Result``; everything after that (status, scans, map, events,
how often to ask, the monthly allowance for paid services) is here, shared.

Opt-in on purpose: only tracking numbers (and your country, for numbers that need one) are sent.
Keys are stored encrypted like mail passwords.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as dt_tz

from django.utils import timezone

from kern import secretbox

from . import events
from .models import Preferences, Shipment

log = logging.getLogger(__name__)

BATCH = 40
EVERY = timedelta(minutes=90)
EVERY_SOON = timedelta(minutes=25)  # out for delivery / due today: check more often
MAX_AGE = timedelta(days=60)  # stop asking about packages this old
ROUND_SECONDS = 30  # one round of lookups stops starting new ones after this; the rest wait a round


class TrackingError(Exception):
    def __init__(self, message: str, code: str = "", status: int = 0):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class Scan:
    utc: datetime | None  # for ordering
    at: str | None  # what to show: the carrier's time, with its offset when known
    text: str
    where: str = ""


@dataclass
class Result:
    """One package as a service reports it, in Kern's terms."""

    status: str | None = None  # mail/packages.py STATUS_LABEL keys, or None when unknown
    scans: list[Scan] = field(default_factory=list)
    expected: date | None = None
    origin: str = ""
    destination: str = ""
    pending: bool = False  # still being looked up: ask again next round


# --- settings --------------------------------------------------------------------------


def _row() -> Preferences:
    row, _ = Preferences.objects.get_or_create(pk=1, defaults={"data": {}})
    return row


def _cfg() -> dict:
    t = dict((_row().data or {}).get("tracking") or {})
    # Settings saved before there was a choice of services: one Parcels key at the top level.
    if t.get("key_enc"):
        t.setdefault("keys", {})[t.get("provider") or "parcels"] = t.pop("key_enc")
        if t.get("limit"):
            t.setdefault("limits", {})["parcels"] = t.pop("limit")
        if t.get("sent"):
            t["sent"] = {"parcels": t["sent"]} if "month" in t["sent"] else t["sent"]
        if t.get("exact") and "month" in t["exact"]:
            t["exact"] = {"parcels": t["exact"]}
    return t


def _save(t: dict) -> None:
    row = _row()
    data = dict(row.data or {})
    data["tracking"] = t
    row.data = data
    row.save(update_fields=["data", "updated"])


def _month() -> str:
    return timezone.localdate().strftime("%Y-%m")


def tracker(name: str | None = None):
    from .trackers import TRACKERS

    t = _cfg()
    return TRACKERS.get(name if name is not None else t.get("provider", ""))


def secret(name: str, t: dict | None = None) -> str:
    """The stored key (or token) for one service, decrypted; "" when none."""
    enc = ((t if t is not None else _cfg()).get("keys") or {}).get(name)
    if not enc:
        return ""
    try:
        return secretbox.decrypt(enc)
    except Exception:  # noqa: BLE001 - a key saved on another server can't be read here
        return ""


def allowance(t: dict | None = None, name: str | None = None) -> dict | None:
    """How many new packages a metered service can still take this cycle (None: not metered)."""
    t = _cfg() if t is None else t
    name = name or t.get("provider", "")
    tr = tracker(name)
    if tr is None or not tr.METERED:
        return None
    limit = int((t.get("limits") or {}).get(name) or tr.FREE_LIMIT)
    month = _month()
    sent = (t.get("sent") or {}).get(name) or {}
    used = len(sent.get("numbers") or []) if sent.get("month") == month else 0
    exact = (t.get("exact") or {}).get(name) or {}
    if exact.get("month") == month:  # the service told us; our own count can only have grown since
        limit = int(exact.get("limit") or limit)
        used = max(used, int(exact.get("current") or 0))
    return {"limit": limit, "used": used, "left": max(0, limit - used), "month": month,
            "exact": exact.get("month") == month}


def settings_json() -> dict:
    from .trackers import TRACKERS

    t = _cfg()
    name = t.get("provider", "")
    tr = TRACKERS.get(name)
    return {
        "provider": name,
        "hasKey": bool(tr and (not tr.NEEDS_KEY or secret(name, t))),
        "keys": {n: bool(secret(n, t)) for n in TRACKERS},
        "country": t.get("country", ""),
        "scraper": {"url": (t.get("scraper") or {}).get("url", ""), "fallbacks": (t.get("scraper") or {}).get("fallbacks", ["UPU"]),
                    "builtIn": TRACKERS["scraper"].built_in()},
        "lastError": t.get("last_error", ""), "lastChecked": t.get("last_checked"),
        "allowance": allowance(t, name) if tr else None,
        "services": [{"id": n, "name": x.LABEL, "needsKey": x.NEEDS_KEY, "metered": x.METERED} for n, x in TRACKERS.items()],
    }


def configure(provider: str, key: str | None = None, country: str | None = None, limit: int | None = None,
              scraper: dict | None = None) -> dict:
    """provider "" turns live tracking off (stored keys stay, for turning it back on); otherwise it
    picks the service. key None keeps the stored one; key "" forgets it."""
    from .trackers import TRACKERS

    if provider and provider not in TRACKERS:
        raise TrackingError("Unknown tracking service.")
    t = _cfg()
    t["provider"] = provider
    if provider:
        tr = TRACKERS[provider]
        keys = t.setdefault("keys", {})
        if key is not None:
            key = key.strip()
            if key and (len(key) > 300 or any(c.isspace() for c in key)):
                raise TrackingError("That doesn't look like an API key.")
            if key:
                keys[provider] = secretbox.encrypt(key)
            else:
                keys.pop(provider, None)
            (t.get("exact") or {}).pop(provider, None)
        if country is not None:
            c = country.strip().upper()
            if c and (len(c) != 2 or not c.isalpha()):
                raise TrackingError("Pick your country (two letters, like US or SE).")
            t["country"] = c
        if limit is not None:
            t.setdefault("limits", {})[provider] = max(1, min(1_000_000, int(limit)))
        if scraper is not None:
            t["scraper"] = tr.clean_settings(scraper, t.get("scraper") or {}) if provider == "scraper" else t.get("scraper")
        if tr.NEEDS_KEY and not keys.get(provider):
            raise TrackingError("Paste your API key.")
    t["last_error"] = ""
    t.pop("pending", None)
    _save(t)
    return settings_json()


def enabled() -> bool:
    t = _cfg()
    tr = tracker(t.get("provider", ""))
    return bool(tr and (not tr.NEEDS_KEY or secret(t["provider"], t)) and tr.available(t))


def note(error: str = "", **changes) -> None:
    t = _cfg()
    if not t:
        return
    t["last_error"] = error[:300]
    t["last_checked"] = timezone.now().isoformat()
    t.update(changes)
    _save(t)


def record_exact(name: str, limit, current) -> None:
    """The service stated its own usage figures (e.g. with a 'limit reached' error)."""
    t = _cfg()
    t.setdefault("exact", {})[name] = {"month": _month(), "limit": limit, "current": current}
    _save(t)


def count_sent(name: str, numbers: list[str]) -> None:
    t = _cfg()
    month = _month()
    sent = (t.get("sent") or {}).get(name) or {}
    have = set(sent.get("numbers") or []) if sent.get("month") == month else set()
    have |= set(numbers)
    t.setdefault("sent", {})[name] = {"month": month, "numbers": sorted(have)}
    _save(t)


def counted(name: str, number: str) -> bool:
    sent = (_cfg().get("sent") or {}).get(name) or {}
    return sent.get("month") == _month() and number in (sent.get("numbers") or [])


def kick() -> None:
    """Check every package soon: the mail worker picks this up within seconds (worker.py), so
    saving settings doesn't wait for slow carriers."""
    Shipment.objects.filter(hidden=False).exclude(status="delivered").update(checked_at=None)
    t = _cfg()
    t["kick"] = timezone.now().isoformat()
    _save(t)


def kicked() -> bool:
    """Whether a check was asked for since the last round (cheap: one row)."""
    t = _cfg()
    return bool(t.get("kick")) and (t.get("last_checked") or "") < t["kick"]


def check_key() -> None:
    """A check that the chosen service answers (with a key: that it's accepted). Uses no quota."""
    t = _cfg()
    tr = tracker(t.get("provider", ""))
    if tr is None:
        return
    tr.check(t)


# --- reading a result ------------------------------------------------------------------------


def parse_when(raw: str | None, offset: str | None = None) -> tuple[datetime | None, str | None]:
    """(UTC instant, the time to show) for a scan time that may carry an offset, or come with one
    separately, or have none (then it's the carrier's local clock, shown as written)."""
    raw = str(raw or "").strip()
    if not raw:
        return None, None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None, None
    if d.tzinfo is None and offset:
        try:
            sign = 1 if offset[0] == "+" else -1
            d = d.replace(tzinfo=dt_tz(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))))
        except (ValueError, IndexError):
            pass
    if d.tzinfo is not None:
        return d.astimezone(dt_tz.utc), d.isoformat()
    return timezone.make_aware(d), d.isoformat()


def status_from(words: list[tuple[str, str]], api_status: str, latest_text: str) -> str | None:
    """Our status from a service's status word and the newest scan's wording."""
    from .packages import detect_status

    a = (api_status or "").lower()
    if "deliver" in a and not any(x in a for x in ("out", "un", "fail", "attempt")):
        return "delivered"
    said = detect_status("", latest_text or "") if latest_text else None
    if said in ("delivered", "out_for_delivery", "ready_for_pickup", "exception"):
        return said
    for needle, ours in words:
        if needle in a:
            return ours
    return said if latest_text else None


def apply(s: Shipment, r: Result) -> bool:
    """Update a shipment from a service's result. Returns whether its status changed."""
    from . import geo

    scans = sorted(r.scans, key=lambda x: x.utc or datetime.min.replace(tzinfo=dt_tz.utc), reverse=True)
    latest = scans[0] if scans else None
    changed = False
    if r.status and r.status != s.status:
        s.status, changed = r.status, True
        s.status_at = (latest and latest.utc) or timezone.now()
    elif latest and latest.utc and (s.status_at is None or latest.utc > s.status_at):
        s.status_at = latest.utc
    if r.expected and s.status != "delivered":
        s.expected, s.expected_text = r.expected, ""
    if s.status == "delivered":
        s.expected, s.expected_text = None, ""
    s.live_events = [{"at": x.at, "text": x.text[:300], "where": x.where[:120]} for x in scans[:30]]
    s.location = latest.where[:120] if latest else ""
    places = [x.where for x in reversed(scans) if x.where]
    s.route = {"origin": r.origin[:120], "destination": r.destination[:120],
               "points": geo.route_points(places) if places else []}
    s.live = True
    s.checked_at = timezone.now()
    return changed


def _due(now) -> list[Shipment]:
    qs = Shipment.objects.filter(hidden=False, first_seen__gte=now - MAX_AGE).exclude(status="delivered")
    out = []
    for s in qs.order_by("checked_at")[:200]:
        soon = s.status in ("out_for_delivery", "ready_for_pickup") or (s.expected and s.expected <= now.date())
        if s.checked_at is None or now - s.checked_at >= (EVERY_SOON if soon else EVERY):
            out.append(s)
    return out[:BATCH]


def store(s: Shipment, r: Result | None, now) -> int:
    """Save one answer; 1 when the package's status changed."""
    if r is None or r.pending:
        if s.checked_at is None or s.checked_at < now:
            s.checked_at = now
            s.save(update_fields=["checked_at"])
        return 0
    before = s.status
    moved = apply(s, r)
    s.save()
    if moved:
        events.emit("package", id=s.pk, status=s.status, thread=s.thread_id, before=before)
    return int(moved)


def skipped(cfg: dict) -> set[str]:
    return set(cfg.get("_skipped") or ())


def out_of_time(cfg: dict) -> bool:
    import time as _time

    return _time.monotonic() > cfg.get("_deadline", float("inf"))


def refresh(shipments: list[Shipment] | None = None, *, force: bool = False) -> int:
    """Ask the chosen service about due (or the given) shipments. Returns how many changed status."""
    t = _cfg()
    name = t.get("provider", "")
    tr = tracker(name)
    if tr is None or (tr.NEEDS_KEY and not secret(name, t)) or not tr.available(t):
        if kicked():
            note(t.get("last_error", ""))  # nothing to do: answer the request so it isn't asked again
        return 0
    now = timezone.now()
    items = shipments if shipments is not None else _due(now)
    if not items and not t.get("pending"):
        if kicked():
            note(t.get("last_error", ""))
        return 0
    try:
        ask, warning = items, ""
        a = allowance(t, name)
        if a is not None:  # a metered service: new numbers only while the allowance lasts
            left, ask = a["left"], []
            for s in items:
                if counted(name, s.number):
                    ask.append(s)
                elif left > 0:
                    left -= 1
                    ask.append(s)
            if items and len(ask) < len(items):
                warning = "This month's allowance is used up. New packages are tracked from emails until it resets."
        import time as _time

        t["_deadline"] = _time.monotonic() + (ROUND_SECONDS if shipments is None else 120)
        results, said = tr.lookup(ask, t) if ask or t.get("pending") else ({}, "")
        # Packages the round had no time for keep their place in the queue for the next one.
        changed = sum(store(s, results.get(s.number), now) for s in ask if s.number in results or s.number not in skipped(t))
        for s in items:
            if s not in ask:
                store(s, None, now)
        note(said or warning)
        return changed
    except TrackingError as e:
        log.info("package tracking (%s): %s", name, e)
        note(str(e))
        if force:
            raise
        for s in items:  # don't hammer a failing service
            store(s, None, now)
        return 0
