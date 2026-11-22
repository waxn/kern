"""Live package tracking with Parcels (parcelsapp.com, API v5).

Shipping emails only say what the shop knew when it wrote them, so a package delivered without a
"delivered" email would stay "on the way" forever. With a Parcels API key (Settings → Mail →
Package tracking) the mail worker asks for each package's real carrier status every so often:
status, expected day, where it is, the latest scans and, for the map, where those scans were
(mail/geo.py).

How the API works (https://parcelsapp.com/developers/docs):

* ``POST /trackings`` with ``shipments: [{tracking_number, carrier_hint | destination_country}]``
  starts one asynchronous lookup and returns ``request_id``, ``done`` and ``results``; results
  already fresh in Parcels' cache come back at once. ``GET /trackings/{request_id}`` is polled
  until ``done`` (records live about 30 minutes). For later checks, POST again.
* Quota: each unique tracking number counts once per billing cycle, however often it's asked
  about again. There is no endpoint that reports usage, so Kern counts the numbers it sent this
  month itself, and takes the exact figures whenever Parcels states them (``SUBSCRIPTION_LIMIT_
  REACHED`` carries limit / current / available). Nothing is sent once the allowance is used up,
  except numbers already counted this cycle (they're free).
* v5 scan times are the carrier's local time; ``utcOffset`` is given only when known.

Opt-in on purpose: only tracking numbers (and your country, for numbers that need one) are sent.
The key is stored encrypted like mail passwords.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone as dt_tz

from django.utils import timezone

from kern import secretbox

from . import events
from .models import Preferences, Shipment

log = logging.getLogger(__name__)

API = "https://parcelsapp.com/api/v5"
TIMEOUT = 25
BATCH = 40
EVERY = timedelta(minutes=90)
EVERY_SOON = timedelta(minutes=25)  # out for delivery / due today: check more often
MAX_AGE = timedelta(days=60)  # stop asking about packages this old
POLL_TRIES, POLL_WAIT = 6, 2.5  # wait up to ~15 s for a lookup to finish, then pick it up next round
FREE_LIMIT = 300

# Our carrier ids (mail/packages.py) -> Parcels' tracking slugs. Without one, Parcels needs the
# destination country to find the carrier.
CARRIER_HINTS = {
    "ups": "ups", "usps": "usps", "fedex": "fedex", "royalmail": "royal-mail", "postnord": "sweden-post",
    "bring": "bring", "gls": "gls", "amazon": "amazon-logistics",
}

# Parcels' shipment.status (free text, e.g. "delivered", "transit") -> ours.
STATUS_WORDS = [
    ("delivered", "delivered"),
    ("out_for_delivery", "out_for_delivery"), ("out for delivery", "out_for_delivery"),
    ("pickup", "ready_for_pickup"), ("ready", "ready_for_pickup"), ("arrived", "ready_for_pickup"),
    ("exception", "exception"), ("fail", "exception"), ("undeliver", "exception"), ("return", "exception"),
    ("transit", "in_transit"), ("shipped", "in_transit"),
    ("pending", "ordered"), ("info", "ordered"), ("created", "ordered"),
]


class TrackingError(Exception):
    def __init__(self, message: str, code: str = "", status: int = 0):
        super().__init__(message)
        self.code, self.status = code, status


# --- settings --------------------------------------------------------------------------


def _row() -> Preferences:
    row, _ = Preferences.objects.get_or_create(pk=1, defaults={"data": {}})
    return row


def _cfg() -> dict:
    return dict((_row().data or {}).get("tracking") or {})


def _save(t: dict) -> None:
    row = _row()
    data = dict(row.data or {})
    data["tracking"] = t
    row.data = data
    row.save(update_fields=["data", "updated"])


def _month() -> str:
    return timezone.localdate().strftime("%Y-%m")


def allowance(t: dict | None = None) -> dict:
    """How many new packages can still be tracked this cycle."""
    t = _cfg() if t is None else t
    limit = int(t.get("limit") or FREE_LIMIT)
    month = _month()
    sent = t.get("sent") or {}
    used = len(sent.get("numbers") or []) if sent.get("month") == month else 0
    exact = t.get("exact") or {}
    if exact.get("month") == month:  # Parcels told us; our own count can only have grown since
        limit = int(exact.get("limit") or limit)
        used = max(used, int(exact.get("current") or 0))
    return {"limit": limit, "used": used, "left": max(0, limit - used), "month": month,
            "exact": exact.get("month") == month}


def settings_json() -> dict:
    t = _cfg()
    return {"provider": t.get("provider", ""), "hasKey": bool(t.get("key_enc")), "country": t.get("country", ""),
            "lastError": t.get("last_error", ""), "lastChecked": t.get("last_checked"),
            "allowance": allowance(t) if t.get("key_enc") else None}


def configure(provider: str, key: str | None, country: str | None = None, limit: int | None = None) -> dict:
    """provider "" turns live tracking off (and forgets the key); "parcels" with a key turns it on.
    key None keeps the stored one."""
    if provider not in ("", "parcels"):
        raise TrackingError("Unknown tracking service.")
    t = _cfg()
    if not provider:
        _save({})
        return settings_json()
    if t.get("provider") != provider:
        t = {}
    t["provider"] = provider
    if key is not None:
        key = key.strip()
        if not key or len(key) > 300 or any(c.isspace() for c in key):
            raise TrackingError("That doesn't look like an API key.")
        t["key_enc"] = secretbox.encrypt(key)
        t.pop("exact", None)
    if not t.get("key_enc"):
        raise TrackingError("Paste your API key.")
    if country is not None:
        c = country.strip().upper()
        if c and (len(c) != 2 or not c.isalpha()):
            raise TrackingError("Pick your country (two letters, like US or SE).")
        t["country"] = c
    if limit is not None:
        t["limit"] = max(1, min(1_000_000, int(limit)))
    t["last_error"] = ""
    _save(t)
    return settings_json()


def _key() -> str:
    t = _cfg()
    if t.get("provider") != "parcels" or not t.get("key_enc"):
        return ""
    try:
        return secretbox.decrypt(t["key_enc"])
    except Exception:  # noqa: BLE001 - a key from another server can't be read here
        return ""


def enabled() -> bool:
    return bool(_key())


def _note(error: str = "", **changes) -> None:
    t = _cfg()
    if not t:
        return
    t["last_error"] = error[:300]
    t["last_checked"] = timezone.now().isoformat()
    t.update(changes)
    _save(t)


def _count_sent(numbers: list[str]) -> None:
    t = _cfg()
    month = _month()
    sent = t.get("sent") or {}
    have = set(sent.get("numbers") or []) if sent.get("month") == month else set()
    have |= set(numbers)
    t["sent"] = {"month": month, "numbers": sorted(have)}
    _save(t)


def _counted(number: str) -> bool:
    sent = _cfg().get("sent") or {}
    return sent.get("month") == _month() and number in (sent.get("numbers") or [])


# --- the service -------------------------------------------------------------------------


def _call(key: str, method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "Kern-Mail/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https URL
            return json.loads(r.read(5_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            err = (json.loads(e.read(200_000).decode("utf-8", "replace")) or {}).get("error") or {}
        except ValueError:
            err = {}
        raise _error(e.code, err) from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise TrackingError("Couldn't reach Parcels.") from e


def _error(status: int, err: dict) -> TrackingError:
    e = _error_text(status, err)
    e.code, e.status = err.get("code") or "", status
    return e


def _error_text(status: int, err: dict) -> TrackingError:
    code = err.get("code") or ""
    if code == "SUBSCRIPTION_LIMIT_REACHED":
        _note("", exact={"month": _month(), "limit": err.get("limit"), "current": err.get("current"),
                         "available": err.get("available")})
        return TrackingError(f"This month's Parcels allowance is used up ({err.get('current')} of {err.get('limit')}).")
    friendly = {
        "MISSING_API_KEY": "Parcels didn't get an API key.",
        "INVALID_API_KEY": "Parcels refused the API key.",
        "UNCONFIRMED_ACCOUNT": "Confirm your Parcels account (check your email), then try again.",
        "SUBSCRIPTION_NOT_FOUND": "That key has no Parcels subscription.",
        "SUBSCRIPTION_INACTIVE": "The Parcels subscription is inactive.",
        "INVALID_SUBSCRIPTION_STATE": "The Parcels subscription can't track right now.",
        "FORBIDDEN": "Tracking is turned off for this Parcels account.",
        "RATE_LIMITED": "Parcels says: too many requests. Trying again later.",
        "BUSY": "Parcels is busy. Trying again later.",
    }
    if code in friendly:
        return TrackingError(friendly[code])
    if status in (401, 403):
        return TrackingError("Parcels refused the API key.")
    return TrackingError(err.get("message") or f"Parcels answered {status}.")


def check_key() -> None:
    """A free call (no quota) that fails when the key is wrong."""
    key = _key()
    if not key:
        raise TrackingError("Paste your API key.")
    _call(key, "GET", "/tracking-carriers?query=ups&limit=1")


def _item(s: Shipment, country: str) -> dict | None:
    hint = CARRIER_HINTS.get(s.carrier)
    if hint:
        return {"tracking_number": s.number, "carrier_hint": hint}
    if country:
        return {"tracking_number": s.number, "destination_country": country}
    return None  # Parcels can't find the carrier without one or the other


# --- reading a result ------------------------------------------------------------------------


def _when(e: dict) -> tuple[datetime | None, str | None]:
    """(UTC instant for ordering, the time to show) for a v5 event."""
    raw = str(e.get("date") or "")
    if not raw:
        return None, None
    try:
        local = datetime.fromisoformat(raw.replace("Z", ""))
    except ValueError:
        return None, None
    off = e.get("utcOffset")
    if off:
        try:
            sign = 1 if off[0] == "+" else -1
            h, m = int(off[1:3]), int(off[4:6])
            aware = local.replace(tzinfo=dt_tz(sign * timedelta(hours=h, minutes=m)))
            return aware.astimezone(dt_tz.utc), aware.isoformat()
        except (ValueError, IndexError):
            pass
    # Offset unknown: Parcels never guesses one. Order by it as if local, show it as written.
    return timezone.make_aware(local), local.isoformat()


def _status(api_status: str, latest_text: str) -> str | None:
    from .packages import detect_status

    a = (api_status or "").lower()
    if "deliver" in a and "out" not in a and "un" not in a:
        return "delivered"
    words = detect_status("", latest_text or "") if latest_text else None
    if words in ("delivered", "out_for_delivery", "ready_for_pickup", "exception"):
        return words
    for needle, ours in STATUS_WORDS:
        if needle in a:
            return ours
    return words if latest_text else None


def apply(s: Shipment, shipment: dict, estimate: dict | None = None) -> bool:
    """Update a shipment from one Parcels result. Returns whether its status changed."""
    from . import geo

    if shipment.get("error"):
        s.checked_at = timezone.now()
        return False
    scans = []
    for e in (shipment.get("states") or [])[:60]:
        utc, shown = _when(e)
        text = " ".join(str(e.get("state") or "").split())[:300]
        if text:
            scans.append({"at": shown, "utc": utc, "text": text, "where": " ".join(str(e.get("location") or "").split())[:120]})
    scans.sort(key=lambda x: x["utc"] or datetime.min.replace(tzinfo=dt_tz.utc), reverse=True)
    latest = scans[0] if scans else None
    status = _status(str(shipment.get("status") or ""), latest["text"] if latest else "")
    changed = False
    if status and status != s.status:
        s.status, changed = status, True
        s.status_at = (latest and latest["utc"]) or timezone.now()
    elif latest and latest["utc"] and (s.status_at is None or latest["utc"] > s.status_at):
        s.status_at = latest["utc"]
    window = ((estimate or {}).get("estimate") or {}).get("estimated_delivery_at") or {}
    exp = window.get("to") or window.get("from")
    if exp and s.status != "delivered":
        try:
            s.expected, s.expected_text = date.fromisoformat(str(exp)[:10]), ""
        except ValueError:
            pass
    if s.status == "delivered":
        s.expected, s.expected_text = None, ""
    s.live_events = [{k: v for k, v in x.items() if k != "utc"} for x in scans[:30]]
    s.location = latest["where"] if latest else ""
    places = [x["where"] for x in reversed(scans) if x["where"]]
    s.route = {"origin": str(shipment.get("origin") or "")[:120], "destination": str(shipment.get("destination") or "")[:120],
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


def _absorb(res: dict, by_number: dict[str, Shipment]) -> tuple[int, list[str]]:
    """Apply completed results. Returns (status changes, numbers still processing)."""
    changed, waiting = 0, []
    for r in res.get("results") or []:
        s = by_number.get(r.get("tracking_number"))
        if s is None:
            continue
        if r.get("state") != "completed" or not r.get("shipment"):
            waiting.append(s.number)
            continue
        before = s.status
        moved = apply(s, r["shipment"], r.get("delivery_estimate"))
        s.save()
        if moved:
            changed += 1
            events.emit("package", id=s.pk, status=s.status, thread=s.thread_id, before=before)
    for r in res.get("rejected") or []:
        s = by_number.get(r.get("tracking_number"))
        if s is not None:
            s.checked_at = timezone.now()
            s.save(update_fields=["checked_at"])
    return changed, waiting


def _poll(key: str, request_id: str, by_number: dict[str, Shipment], tries: int) -> tuple[int, bool]:
    changed = 0
    for _ in range(tries):
        time.sleep(POLL_WAIT)
        try:
            res = _call(key, "GET", f"/trackings/{request_id}")
        except TrackingError as e:
            if e.status == 404 or e.code == "NO_REQUEST_FOUND":
                return changed, True  # the record expired: the next round asks again
            raise
        n, waiting = _absorb(res, by_number)
        changed += n
        if res.get("done") or not waiting:
            return changed, True
    return changed, False


def refresh(shipments: list[Shipment] | None = None, *, force: bool = False) -> int:
    """Ask Parcels about due (or the given) shipments. Returns how many changed status."""
    key = _key()
    if not key:
        return 0
    t = _cfg()
    now = timezone.now()
    changed = 0
    try:
        # A lookup left processing last time.
        pending = t.get("pending") or {}
        if pending.get("request_id") and shipments is None:
            by_number = {s.number: s for s in Shipment.objects.filter(number__in=pending.get("numbers") or [])}
            n, finished = _poll(key, pending["request_id"], by_number, 1)
            changed += n
            if finished or now.timestamp() - float(pending.get("at") or 0) > 1800:
                t = _cfg()
                t.pop("pending", None)
                _save(t)
        items = shipments if shipments is not None else _due(now)
        if not items:
            return changed
        left = allowance()["left"]
        country = _cfg().get("country", "")
        ask, new = [], 0
        for s in items:
            item = _item(s, country)
            if item is None:
                continue
            if not _counted(s.number):
                if new >= left:
                    continue  # out of allowance: only numbers already counted this cycle are free
                new += 1
            ask.append((s, item))
        if not ask:
            if any(_item(s, country) is None for s in items):
                _note("Set your country so Parcels can find the carrier for some packages.")
            elif items and left <= 0:
                _note("This month's allowance is used up. Packages are tracked from emails until it resets.")
            for s in items:  # don't look at them again every round
                s.checked_at = now
                s.save(update_fields=["checked_at"])
            return changed
        by_number = {s.number: s for s, _ in ask}
        res = _call(key, "POST", "/trackings", {"language": "en", "shipments": [i for _, i in ask]})
        rejected = {r.get("tracking_number") for r in res.get("rejected") or []}
        _count_sent([n for n in by_number if n not in rejected])
        n, waiting = _absorb(res, by_number)
        changed += n
        if waiting and not res.get("done") and res.get("request_id"):
            n, finished = _poll(key, res["request_id"], by_number, POLL_TRIES)
            changed += n
            if not finished:
                t = _cfg()
                t["pending"] = {"request_id": res["request_id"], "numbers": waiting, "at": now.timestamp()}
                _save(t)
        for s in by_number.values():  # asked even if nothing came back yet: wait a round
            if s.checked_at is None or s.checked_at < now:
                s.checked_at = now
                s.save(update_fields=["checked_at"])
        _note("")
    except TrackingError as e:
        log.info("package tracking: %s", e)
        _note(str(e))
        if force:
            raise
        for s in shipments if shipments is not None else _due(now):  # don't hammer a failing service
            s.checked_at = now
            s.save(update_fields=["checked_at"])
    return changed
