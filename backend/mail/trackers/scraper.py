"""Universal Parcel Scraper: Peek's open-source tracking engine (github.com/plhery/universal-parcel-scraper).

It reads each carrier's own tracking site and answers with the same JSON for every carrier: no
account, no API key, nothing metered. Two ways to reach it:

* Built in: Kern's Docker image carries it (Node and the npm package, see backend/Dockerfile),
  and the mail worker runs ``parcel-scraper track <number> [--carrier <id>]`` per lookup.
* Your own: its HTTP server (``parcel-scraper serve``, or its Docker image with Chromium for the
  carriers that only answer a browser) at a URL you give, ``POST /v1/track``, with its
  ``SCRAPER_TOKEN`` if you set one. The host must be public unless an administrator allows local
  servers (Settings → Server), like mail servers.

A lookup sends the number to the carrier. Universal trackers it falls back on are opt-in
(``fallbacks``; only UPU by default) and each one you enable gets the number too.

Licence: the package is Apache-2.0 up to 0.1293.2 and PolyForm Noncommercial from 0.1294.0;
the image pins a version (backend/Dockerfile).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date
from urllib.parse import urlsplit

from .base import Tracker

FALLBACKS = ["UPU", "ParcelsApp", "Ship24", "17TRACK", "Ordertracker", "Postal Ninja", "Track718"]
TIMEOUT = 45  # one lookup; a round stops starting new ones after tracking.ROUND_SECONDS

# Our carrier ids -> the scraper catalog's ids (it detects the rest itself).
CARRIERS = {"ups": "ups", "usps": "usps", "fedex": "fedex", "royalmail": "royal-mail", "postnord": "postnord",
            "bring": "bring-posten", "amazon": "amazon-logistics"}

# The scraper's stages (data/stages.json) -> ours.
STAGES = {
    "pending": "ordered", "registered": "ordered", "accepted": "in_transit", "in_transit": "in_transit",
    "customs": "in_transit", "out_for_delivery": "out_for_delivery", "delivered": "delivered",
    "failed_attempt": "exception", "ready_for_pickup": "ready_for_pickup", "returned": "exception", "exception": "exception",
}


def binary() -> str:
    """The built-in scraper (the image's script, or a parcel-scraper command), if this install has it."""
    path = os.environ.get("KERN_PARCEL_SCRAPER")
    if path and os.path.exists(path) and (not path.endswith(".js") or shutil.which("node")):
        return path
    return shutil.which("parcel-scraper") or ""


def result_of(answer: dict):
    from .. import tracking

    r = answer.get("result") if isinstance(answer.get("result"), dict) else {}
    scans = []
    for e in (r.get("events") or [])[:80]:
        if not isinstance(e, dict):
            continue
        utc, _ = tracking.parse_when(e.get("instant"))
        shown = e.get("time") or e.get("instant")
        if utc is None:
            utc, shown2 = tracking.parse_when(e.get("time"))
            shown = shown2 or shown
        text = " ".join(str(e.get("description") or "").split())
        if text:
            scans.append(tracking.Scan(utc, shown, text, " ".join(str(e.get("location") or "").split())))
    scans.sort(key=lambda x: x.utc.timestamp() if x.utc else 0, reverse=True)
    status = STAGES.get(str(r.get("current_stage") or ""))
    if status is None and scans:
        status = tracking.status_from([], "", scans[0].text)
    exp = r.get("expected_delivery")
    try:
        expected = date.fromisoformat(str(exp)[:10]) if exp else None
    except ValueError:
        expected = None
    return tracking.Result(status=status, scans=scans, expected=expected,
                           destination=str(r.get("destination_country") or ""))


class Scraper(Tracker):
    LABEL = "Universal Parcel Scraper"
    NEEDS_KEY = False
    METERED = False

    @classmethod
    def built_in(cls) -> bool:
        return bool(binary())

    @classmethod
    def available(cls, cfg: dict) -> bool:
        return bool((cfg.get("scraper") or {}).get("url")) or cls.built_in()

    @classmethod
    def clean_settings(cls, new: dict, old: dict) -> dict:
        from .. import hosts, tracking

        out = dict(old)
        if "url" in new:
            url = str(new.get("url") or "").strip().rstrip("/")
            if url:
                parts = urlsplit(url)
                if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                    raise tracking.TrackingError("Enter the scraper's address, like http://parcels.example.com:8080.")
                try:
                    hosts.check(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
                except hosts.HostNotAllowed as exc:
                    raise tracking.TrackingError(str(exc)) from exc
            out["url"] = url
        if "fallbacks" in new:
            out["fallbacks"] = [f for f in FALLBACKS if f in (new.get("fallbacks") or [])] or ["UPU"]
        return out

    @classmethod
    def _remote(cls, cfg: dict, payload: dict) -> dict | None:
        from .. import hosts, tracking

        url = (cfg.get("scraper") or {}).get("url")
        parts = urlsplit(url)
        try:
            hosts.check(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        except hosts.HostNotAllowed as exc:
            raise tracking.TrackingError(str(exc)) from exc
        token = tracking.secret("scraper", cfg)

        def error(status, body):
            if status == 404:
                return _NotFound()
            if status == 401:
                return tracking.TrackingError("The scraper wants its token (SCRAPER_TOKEN).", status=401)
            if status == 429:
                return tracking.TrackingError("The scraper is busy or rate-limited. Trying again later.", status=429)
            e = tracking.TrackingError(str(body.get("error") or f"The scraper answered {status}.")[:200], status=status)
            e.code = str(body.get("field") or "")
            return e

        try:
            return cls.http_json(url + "/v1/track", method="POST", body=payload, timeout=TIMEOUT,
                                 headers={"Authorization": f"Bearer {token}"} if token else {}, error=error)
        except _NotFound:
            return None

    @classmethod
    def _local(cls, cfg: dict, number: str, carrier: str | None) -> dict | None:
        from .. import tracking

        exe = binary()
        # The image points at the package's script (run with Node); a global install has a command.
        cmd = (["node", exe] if exe.endswith(".js") else [exe]) + ["track", number] + (["--carrier", carrier] if carrier else [])
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
               "SCRAPER_PROVIDERS": ",".join((cfg.get("scraper") or {}).get("fallbacks") or ["UPU"]),
               "SCRAPER_USER_AGENT": "Kern-Mail/1 (self-hosted mail client)"}
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, env=env, check=False)  # noqa: S603 - fixed argv
        except (OSError, subprocess.TimeoutExpired) as e:
            raise tracking.TrackingError("The built-in scraper didn't answer.") from e
        if p.returncode != 0:
            return None  # no source knows the parcel (yet), or the carrier turned the lookup away
        try:
            return json.loads(p.stdout.decode("utf-8", "replace"))
        except ValueError as e:
            raise tracking.TrackingError("The built-in scraper's answer couldn't be read.") from e

    @classmethod
    def check(cls, cfg: dict) -> None:
        from .. import tracking

        if (cfg.get("scraper") or {}).get("url"):
            url = cfg["scraper"]["url"]
            cls.http_json(url + "/health", timeout=10,
                          error=lambda s, b: tracking.TrackingError(f"The scraper at {urlsplit(url).hostname} answered {s}."))
        elif not cls.built_in():
            raise tracking.TrackingError("This Kern has no built-in scraper. Rebuild the Docker image, or enter the address of one you run.")

    @classmethod
    def lookup(cls, shipments, cfg: dict):
        from .. import tracking

        out: dict = {}
        remote = bool((cfg.get("scraper") or {}).get("url"))
        cfg["_skipped"] = []
        for s in shipments:
            if tracking.out_of_time(cfg):
                cfg["_skipped"].append(s.number)  # next round
                continue
            carrier = CARRIERS.get(s.carrier)
            answer = cls._remote(cfg, {"number": s.number, **({"carrier": carrier} if carrier else {})}) if remote \
                else cls._local(cfg, s.number, carrier)
            if answer:
                out[s.number] = result_of(answer)
        return out, ""


class _NotFound(Exception):
    pass
