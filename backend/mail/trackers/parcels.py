"""Parcels (parcelsapp.com, API v5): https://parcelsapp.com/developers/docs

* ``POST /trackings`` with ``shipments: [{tracking_number, carrier_hint | destination_country}]``
  starts one asynchronous lookup and returns ``request_id``, ``done`` and ``results``; results
  already fresh in Parcels' cache come back at once. ``GET /trackings/{request_id}`` is polled
  until ``done`` (records live about 30 minutes). For later checks, POST again.
* Quota: each unique tracking number counts once per billing cycle, however often it's asked
  about. There's no usage endpoint, so Kern counts what it sent (mail/tracking.py), and takes the
  exact figures whenever Parcels states them (``SUBSCRIPTION_LIMIT_REACHED``).
* v5 scan times are the carrier's local time; ``utcOffset`` is given only when known.
"""

from __future__ import annotations

import time
from datetime import date

from django.utils import timezone

from .base import Tracker

API = "https://parcelsapp.com/api/v5"
POLL_TRIES, POLL_WAIT = 6, 2.5  # wait up to ~15 s for a lookup, then pick it up next round

# Our carrier ids (mail/packages.py) -> Parcels' tracking slugs. Without one, Parcels needs the
# destination country to find the carrier.
CARRIER_HINTS = {
    "ups": "ups", "usps": "usps", "fedex": "fedex", "royalmail": "royal-mail", "postnord": "sweden-post",
    "bring": "bring", "gls": "gls", "amazon": "amazon-logistics",
}

# Parcels' shipment.status (free text, e.g. "delivered", "transit") -> ours.
STATUS_WORDS = [
    ("out_for_delivery", "out_for_delivery"), ("out for delivery", "out_for_delivery"),
    ("pickup", "ready_for_pickup"), ("ready", "ready_for_pickup"), ("arrived", "ready_for_pickup"),
    ("exception", "exception"), ("fail", "exception"), ("undeliver", "exception"), ("return", "exception"),
    ("transit", "in_transit"), ("shipped", "in_transit"),
    ("pending", "ordered"), ("info", "ordered"), ("created", "ordered"),
]

FRIENDLY = {
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


def _error(status: int, body: dict):
    from .. import tracking

    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = err.get("code") or ""
    if code == "SUBSCRIPTION_LIMIT_REACHED":
        tracking.record_exact("parcels", err.get("limit"), err.get("current"))
        e = tracking.TrackingError(f"This month's Parcels allowance is used up ({err.get('current')} of {err.get('limit')}).")
    elif code in FRIENDLY:
        e = tracking.TrackingError(FRIENDLY[code])
    elif status in (401, 403):
        e = tracking.TrackingError("Parcels refused the API key.")
    else:
        e = tracking.TrackingError(err.get("message") or f"Parcels answered {status}.")
    e.code, e.status = code, status
    return e


def _call(key: str, method: str, path: str, payload: dict | None = None) -> dict:
    return Parcels.http_json(API + path, method=method, body=payload, headers={"Authorization": f"Bearer {key}"},
                             error=_error)


def result_of(shipment: dict, estimate: dict | None = None):
    from .. import tracking

    if shipment.get("error"):
        return None
    scans = []
    for e in (shipment.get("states") or [])[:60]:
        utc, shown = tracking.parse_when(e.get("date"), e.get("utcOffset"))
        text = " ".join(str(e.get("state") or "").split())
        if text:
            scans.append(tracking.Scan(utc, shown, text, " ".join(str(e.get("location") or "").split())))
    scans.sort(key=lambda x: x.utc.timestamp() if x.utc else 0, reverse=True)
    window = ((estimate or {}).get("estimate") or {}).get("estimated_delivery_at") or {}
    exp = window.get("to") or window.get("from")
    try:
        expected = date.fromisoformat(str(exp)[:10]) if exp else None
    except ValueError:
        expected = None
    return tracking.Result(
        status=tracking.status_from(STATUS_WORDS, str(shipment.get("status") or ""), scans[0].text if scans else ""),
        scans=scans, expected=expected,
        origin=str(shipment.get("origin") or ""), destination=str(shipment.get("destination") or ""))


class Parcels(Tracker):
    LABEL = "Parcels"
    FREE_LIMIT = 300

    @classmethod
    def check(cls, cfg: dict) -> None:
        from .. import tracking

        _call(tracking.secret("parcels", cfg), "GET", "/tracking-carriers?query=ups&limit=1")

    @classmethod
    def _absorb(cls, res: dict, out: dict) -> list[str]:
        waiting = []
        for r in res.get("results") or []:
            n = r.get("tracking_number")
            if r.get("state") != "completed" or not r.get("shipment"):
                waiting.append(n)
                continue
            out[n] = result_of(r["shipment"], r.get("delivery_estimate"))
        return waiting

    @classmethod
    def _poll(cls, key: str, request_id: str, out: dict, tries: int) -> bool:
        from .. import tracking

        for _ in range(tries):
            time.sleep(POLL_WAIT)
            try:
                res = _call(key, "GET", f"/trackings/{request_id}")
            except tracking.TrackingError as e:
                if e.status == 404 or e.code == "NO_REQUEST_FOUND":
                    return True  # the record expired: the next round asks again
                raise
            waiting = cls._absorb(res, out)
            if res.get("done") or not waiting:
                return True
        return False

    @classmethod
    def lookup(cls, shipments, cfg: dict):
        from .. import tracking
        from ..models import Shipment

        key = tracking.secret("parcels", cfg)
        out: dict = {}
        now = timezone.now()
        # A lookup left processing last time.
        pending = cfg.get("pending") or {}
        if pending.get("request_id"):
            finished = cls._poll(key, pending["request_id"], out, 1)
            for s in Shipment.objects.filter(number__in=[n for n in out if n not in {x.number for x in shipments}]):
                tracking.store(s, out[s.number], now)
            if finished or now.timestamp() - float(pending.get("at") or 0) > 1800:
                tracking.note(pending=None)
        country = cfg.get("country", "")
        items, warning = [], ""
        for s in shipments:
            hint = CARRIER_HINTS.get(s.carrier)
            if hint:
                items.append({"tracking_number": s.number, "carrier_hint": hint})
            elif country:
                items.append({"tracking_number": s.number, "destination_country": country})
            else:
                warning = "Set your country so Parcels can find the carrier for some packages."
        if not items:
            return out, warning
        res = _call(key, "POST", "/trackings", {"language": "en", "shipments": items})
        rejected = {r.get("tracking_number") for r in res.get("rejected") or []}
        tracking.count_sent("parcels", [i["tracking_number"] for i in items if i["tracking_number"] not in rejected])
        waiting = cls._absorb(res, out)
        if waiting and not res.get("done") and res.get("request_id"):
            if not cls._poll(key, res["request_id"], out, POLL_TRIES):
                left = [n for n in waiting if n not in out]
                tracking.note(warning, pending={"request_id": res["request_id"], "numbers": left, "at": now.timestamp()})
        return out, warning
