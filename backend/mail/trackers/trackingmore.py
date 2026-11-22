"""TrackingMore (trackingmore.com, API v4): https://www.trackingmore.com/docs/trackingmore/

* Header ``Tracking-Api-Key``; base ``https://api.trackingmore.com/v4``.
* ``POST /trackings/create {tracking_number, courier_code}`` adds a package and answers with its
  tracking at once ("create & get"). That costs a credit, once per number. Later checks are
  ``GET /trackings/get?tracking_numbers=…&courier_code=…`` (free; TrackingMore keeps polling the
  carrier itself).
* ``POST /couriers/detect {tracking_number}`` names the carrier when we can't.
* Answers come wrapped as ``{meta|code…, data}``. Field names vary a little between documents
  (``delivery_status`` / ``status``, ``latest_event`` / ``last_event``, scan wording in
  ``tracking_detail`` / ``checkpoint_status``), so both are read.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from .base import Tracker

API = "https://api.trackingmore.com/v4"

# Our carrier ids -> TrackingMore courier codes we're sure of; the rest are detected.
COURIERS = {"ups": "ups", "usps": "usps", "fedex": "fedex", "royalmail": "royal-mail"}

STATUS_WORDS = [
    ("pickup", "ready_for_pickup"), ("undelivered", "exception"), ("exception", "exception"),
    ("expired", "exception"), ("transit", "in_transit"), ("inforeceived", "ordered"), ("pending", "ordered"),
]


def _meta(body: dict) -> tuple[int, str]:
    m = body.get("meta") if isinstance(body.get("meta"), dict) else body
    try:
        code = int(m.get("code") or 0)
    except (TypeError, ValueError):
        code = 0
    return code, str(m.get("message") or "")


def _error(status: int, body: dict):
    from .. import tracking

    code, msg = _meta(body)
    if status in (401, 403) or code in (401, 4011, 4012):
        e = tracking.TrackingError("TrackingMore refused the API key.")
    elif status == 429 or code == 429:
        e = tracking.TrackingError("TrackingMore says: too many requests. Trying again later.")
    elif status == 402 or "credit" in msg.lower() or "quota" in msg.lower() or "balance" in msg.lower():
        e = tracking.TrackingError("Your TrackingMore credits are used up.")
    else:
        e = tracking.TrackingError(msg or f"TrackingMore answered {status}.")
    e.code, e.status = str(code or ""), status
    return e


def _call(key: str, method: str, path: str, body=None) -> dict:
    res = TrackingMore.http_json(API + path, method=method, body=body, headers={"Tracking-Api-Key": key}, error=_error)
    code, _ = _meta(res)
    if code and code != 200:
        raise _error(200, res)
    return res


def result_of(item: dict):
    from .. import tracking

    scans = []
    for side in ("origin_info", "destination_info"):
        for e in ((item.get(side) or {}).get("trackinfo") or [])[:60]:
            utc, shown = tracking.parse_when(e.get("checkpoint_date") or e.get("Date"))
            text = " ".join(str(e.get("tracking_detail") or e.get("StatusDescription") or e.get("checkpoint_status") or "").split())
            where = " ".join(str(e.get("location") or e.get("Details") or "").split())
            if text and not any(x.text == text and x.at == shown for x in scans):
                scans.append(tracking.Scan(utc, shown, text, where))
    scans.sort(key=lambda x: x.utc.timestamp() if x.utc else 0, reverse=True)
    latest = scans[0].text if scans else str(item.get("latest_event") or item.get("last_event") or "")
    exp = item.get("scheduled_delivery_date") or item.get("expected_delivery")
    try:
        expected = date.fromisoformat(str(exp)[:10]) if exp else None
    except ValueError:
        expected = None
    status = str(item.get("delivery_status") or item.get("status") or "")
    if status == "notfound" and not scans:
        return tracking.Result(pending=True)
    return tracking.Result(status=tracking.status_from(STATUS_WORDS, status, latest), scans=scans, expected=expected,
                           origin=str(item.get("origin_country") or ""), destination=str(item.get("destination_country") or ""))


class TrackingMore(Tracker):
    LABEL = "TrackingMore"
    FREE_LIMIT = 50

    @classmethod
    def check(cls, cfg: dict) -> None:
        from .. import tracking

        _call(tracking.secret("trackingmore", cfg), "GET", "/couriers/all")

    @classmethod
    def _courier(cls, key: str, s) -> str:
        if s.carrier in COURIERS:
            return COURIERS[s.carrier]
        res = _call(key, "POST", "/couriers/detect", {"tracking_number": s.number})
        found = res.get("data") or []
        return (found[0] or {}).get("courier_code", "") if found and isinstance(found[0], dict) else ""

    @classmethod
    def lookup(cls, shipments, cfg: dict):
        from .. import tracking

        key = tracking.secret("trackingmore", cfg)
        out: dict = {}
        warning = ""
        known = cfg.get("tm_couriers") or {}  # number -> courier code, so detection runs once
        for s in shipments:
            code = known.get(s.number) or cls._courier(key, s)
            if not code:
                warning = "TrackingMore couldn't tell which carrier some packages are with."
                continue
            known[s.number] = code
            if tracking.counted("trackingmore", s.number):
                res = _call(key, "GET", "/trackings/get?" + urlencode({"tracking_numbers": s.number, "courier_code": code}))
                data = res.get("data") or []
                item = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
            else:
                try:
                    res = _call(key, "POST", "/trackings/create", {"tracking_number": s.number, "courier_code": code})
                    item = res.get("data")
                except tracking.TrackingError as e:
                    if "exist" not in str(e).lower():  # already added (on another device, say): read it
                        raise
                    res = _call(key, "GET", "/trackings/get?" + urlencode({"tracking_numbers": s.number, "courier_code": code}))
                    data = res.get("data") or []
                    item = data[0] if isinstance(data, list) and data else None
                tracking.count_sent("trackingmore", [s.number])
            if isinstance(item, dict):
                out[s.number] = result_of(item)
        tracking.note(warning, tm_couriers=dict(list(known.items())[-500:]))
        return out, warning
