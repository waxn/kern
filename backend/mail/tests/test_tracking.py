"""Live package tracking with Parcels (mail/tracking.py), the service and the map faked."""

from datetime import timedelta

import pytest
from django.utils import timezone

from mail import geo, tracking
from mail.models import ChangeEvent, GeoPlace, Shipment
from mail.trackers import parcels as parcels_mod, scraper as scraper_mod, trackingmore as tm_mod

USPS = "9400111202555842332669"


@pytest.fixture
def ship(db):
    return Shipment.objects.create(carrier="usps", number=USPS, status="in_transit",
                                   status_at=timezone.now() - timedelta(days=3), subject="Your order shipped")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Places resolve from a little table; tiles are fake PNGs. Nothing leaves the test."""
    where = {"Portland, OR, United States": (45.52, -122.68), "Austin, TX, United States": (30.27, -97.74)}
    monkeypatch.setattr(geo, "lookup", lambda name, budget=None: where.get(geo.clean_place(name)))
    monkeypatch.setattr(parcels_mod, "POLL_WAIT", 0)


def delivered(number=USPS):
    return {"tracking_number": number, "state": "completed", "from_cache": True, "shipment": {
        "status": "delivered", "origin": "United States", "destination": "United States",
        "states": [
            {"state": "Delivered, In/At Mailbox", "location": "Austin, TX, United States", "date": "2026-11-20T13:42:00", "utcOffset": "-05:00"},
            {"state": "Out for Delivery", "location": "Austin, TX, United States", "date": "2026-11-20T07:15:00", "utcOffset": "-05:00"},
            {"state": "Accepted at USPS Origin Facility", "location": "Portland, OR, United States", "date": "2026-11-17T14:30:00"},
        ]}}


@pytest.fixture
def fake(monkeypatch):
    calls, answers = [], {}

    def call(key, method, path, payload=None):
        calls.append((key, method, path, payload))
        hit = answers.get((method, path.split("?")[0]))
        if isinstance(hit, Exception):
            raise hit
        if callable(hit):
            return hit(payload)
        if hit is not None:
            return hit
        return {"request_id": "r1", "done": True, "results": []}

    monkeypatch.setattr(parcels_mod, "_call", call)
    return calls, answers


def test_off_without_a_key(ship, fake):
    calls, _ = fake
    assert not tracking.enabled()
    assert tracking.refresh() == 0
    assert calls == []


def test_key_is_stored_encrypted(db):
    out = tracking.configure("parcels", "PK_live_123", country="se")
    assert out["provider"] == "parcels" and out["hasKey"] and out["country"] == "SE" and out["keys"]["parcels"]
    assert out["allowance"] == {"limit": 300, "used": 0, "left": 300, "month": timezone.localdate().strftime("%Y-%m"), "exact": False}
    from mail.models import Preferences

    assert "PK_live_123" not in str(Preferences.objects.get(pk=1).data)
    assert tracking.secret("parcels") == "PK_live_123"
    with pytest.raises(tracking.TrackingError):
        tracking.configure("parcels", "has spaces in it")
    with pytest.raises(tracking.TrackingError):
        tracking.configure("parcels", None, country="Sweden")
    assert tracking.configure("", None)["provider"] == ""
    assert not tracking.enabled()


def test_delivered_by_the_carrier(ship, fake):
    calls, answers = fake
    tracking.configure("parcels", "KEY")
    answers[("POST", "/trackings")] = {"request_id": "r1", "done": True, "results": [delivered()]}
    assert tracking.refresh() == 1
    ship.refresh_from_db()
    assert ship.status == "delivered" and ship.live
    assert ship.location == "Austin, TX, United States"
    assert ship.live_events[0]["text"] == "Delivered, In/At Mailbox"
    assert ship.live_events[0]["at"] == "2026-11-20T13:42:00-05:00"  # the carrier's local time, offset kept
    assert ship.live_events[2]["at"] == "2026-11-17T14:30:00"  # offset unknown: shown as written
    assert ship.status_at.isoformat().startswith("2026-11-20T18:42:00")  # UTC
    # The map: scan places, oldest first, repeats collapsed.
    assert [p[2] for p in ship.route["points"]] == ["Portland, OR, United States", "Austin, TX, United States"]
    # What was sent: the number with the carrier, nothing else.
    key, method, path, payload = calls[0]
    assert (key, method, path) == ("KEY", "POST", "/trackings")
    assert payload["shipments"] == [{"tracking_number": USPS, "carrier_hint": "usps"}]
    assert ChangeEvent.objects.filter(kind="package", data__status="delivered").exists()
    assert tracking.allowance()["used"] == 1
    calls.clear()
    assert tracking.refresh() == 0 and calls == []  # delivered: never asked again


def test_slow_lookup_is_polled(ship, fake):
    calls, answers = fake
    tracking.configure("parcels", "KEY")
    answers[("POST", "/trackings")] = {"request_id": "r9", "done": False,
                                       "results": [{"tracking_number": USPS, "state": "processing", "from_cache": False}]}
    answers[("GET", "/trackings/r9")] = {"request_id": "r9", "done": True, "results": [delivered()]}
    assert tracking.refresh() == 1
    assert [c[2] for c in calls] == ["/trackings", "/trackings/r9"]


def test_numbers_without_carrier_need_a_country(db, fake):
    calls, answers = fake
    s = Shipment.objects.create(carrier="dhl", number="1234567890", status="in_transit", status_at=timezone.now())
    tracking.configure("parcels", "KEY")
    tracking.refresh()
    assert calls == []
    assert "country" in tracking.settings_json()["lastError"]
    tracking.configure("parcels", None, country="DE")
    s.checked_at = None
    s.save()
    tracking.refresh()
    assert calls[-1][3]["shipments"] == [{"tracking_number": "1234567890", "destination_country": "DE"}]


def test_allowance_is_respected(db, fake):
    calls, answers = fake
    tracking.configure("parcels", "KEY", limit=2)
    for i in range(4):
        Shipment.objects.create(carrier="ups", number=f"1Z{i}", status="in_transit", status_at=timezone.now())
    tracking.refresh()
    assert len(calls[0][3]["shipments"]) == 2  # only as many new numbers as are left
    assert tracking.allowance()["left"] == 0
    assert "used up" in tracking.settings_json()["lastError"]
    # Numbers already counted this cycle stay free to ask about again.
    Shipment.objects.update(checked_at=None)
    calls.clear()
    tracking.refresh()
    assert {i["tracking_number"] for i in calls[0][3]["shipments"]} == {"1Z0", "1Z1"}


def test_exact_quota_from_parcels(ship, fake):
    _, answers = fake
    tracking.configure("parcels", "KEY")
    err = parcels_mod._error(402, {"error": {"code": "SUBSCRIPTION_LIMIT_REACHED", "limit": 300, "current": 299, "available": 1}})
    answers[("POST", "/trackings")] = err
    assert tracking.refresh() == 0
    a = tracking.allowance()
    assert a["exact"] and a["used"] == 299 and a["left"] == 1
    assert "used up" in tracking.settings_json()["lastError"]


def test_bad_key(ship, fake):
    _, answers = fake
    tracking.configure("parcels", "KEY")
    answers[("POST", "/trackings")] = parcels_mod._error(401, {"error": {"code": "INVALID_API_KEY", "message": "x"}})
    tracking.refresh()
    assert tracking.settings_json()["lastError"] == "Parcels refused the API key."
    with pytest.raises(tracking.TrackingError):
        tracking.refresh([ship], force=True)


def test_api_settings_and_refresh(api, ship, fake):
    _, answers = fake
    assert api.get("/api/mail/packages/tracking").json()["hasKey"] is False
    r = api.post("/api/mail/packages/tracking", {"provider": "parcels", "key": "KEY", "country": "US"})
    assert r.status_code == 200, r.content
    assert r.json()["hasKey"] and r.json()["allowance"]["limit"] == 300
    answers[("POST", "/trackings")] = {"request_id": "r1", "done": True, "results": [delivered()]}
    ship.checked_at = None
    ship.save()
    p = api.post(f"/api/mail/packages/{ship.id}", {"action": "refresh"}).json()
    assert p["live"] is True and p["status"] == "delivered" and len(p["route"]["points"]) == 2
    assert api.post("/api/mail/packages/tracking", {"provider": ""}).json()["hasKey"] is False


def test_overdue_without_news_counts_as_delivered(api, ship):
    old = timezone.now() - timedelta(days=6)
    Shipment.objects.filter(pk=ship.pk).update(expected=(old + timedelta(days=1)).date(), status_at=old)
    r = api.get("/api/mail/packages").json()
    assert not r["active"]
    assert r["delivered"][0]["assumed"] is True and r["delivered"][0]["status"] == "delivered"
    assert api.get("/api/mail/today").json()["packages"] == []


def test_places_are_cached(db, monkeypatch):
    import json
    import urllib.request

    monkeypatch.undo()  # the real lookup, with the network faked
    hits = []

    class R:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return self.data

    def fake_open(req, timeout=None):
        hits.append(req.full_url)
        assert req.full_url.startswith("https://nominatim.openstreetmap.org/search?")
        return R(json.dumps([{"lat": "55.6", "lon": "13.0"}]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(geo, "_last_lookup", 0.0)
    assert geo.lookup("SE-21119 Malmö, Sweden") == (55.6, 13.0)
    assert geo.lookup("Malmö, Sweden") == (55.6, 13.0)
    assert len(hits) == 1 and GeoPlace.objects.count() == 1
    assert geo.lookup("Nowhere", budget=[0]) is None and len(hits) == 1


def test_tiles_are_checked_and_cached(api, monkeypatch, settings, tmp_path):
    import urllib.request

    settings.DATA_DIR = tmp_path
    got = []

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return b"\x89PNG fake"

    def fake_open(req, timeout=None):
        got.append(req.full_url)
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    r = api.get("/api/mail/maptiles/dark/3/2/1.png")
    assert r.status_code == 200 and r["Content-Type"] == "image/png" and r.content.startswith(b"\x89PNG")
    assert got[0] == "https://tile.openstreetmap.org/3/2/1.png"  # no key: OpenStreetMap
    m = api.get("/api/mail/packages/map").json()
    assert m["provider"] == "osm" and m["tone"] is True and {x["id"] for x in m["sources"]} >= {"osm", "esri", "stadia", "mapbox", "custom"}
    api.get("/api/mail/maptiles/dark/3/2/1.png")
    assert len(got) == 1  # cached
    assert api.get("/api/mail/maptiles/dark/3/9/1.png").status_code == 404  # off the map
    assert api.get("/api/mail/maptiles/neon/3/2/1.png").status_code == 404


def test_maptiler_key(api, monkeypatch, settings, tmp_path):
    import urllib.error
    import urllib.request

    settings.DATA_DIR = tmp_path
    seen = []

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return b"\x89PNG tile"

    def fake_open(req, timeout=None):
        seen.append(req.full_url)
        if "key=bad" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    assert api.post("/api/mail/packages/map", {"key": "bad"}).status_code == 400
    r = api.post("/api/mail/packages/map", {"key": "good"}).json()
    assert r["provider"] == "maptiler" and "MapTiler" in r["attribution"]
    from mail.models import Preferences

    assert "good" not in str(Preferences.objects.get(pk=1).data)
    api.get("/api/mail/maptiles/light/2/1/1.png")
    assert seen[-1] == "https://api.maptiler.com/maps/dataviz/256/2/1/1.png?key=good"
    assert api.post("/api/mail/packages/map", {"key": ""}).json()["provider"] == "osm"
    # The other keyed sources: the key goes in their own parameter.
    for provider, frag in (("stadia", "tiles.stadiamaps.com/tiles/alidade_smooth/2/1/1.png?api_key=good"),
                           ("thunderforest", "tile.thunderforest.com/atlas/2/1/1.png?apikey=good"),
                           ("mapbox", "api.mapbox.com/styles/v1/mapbox/light-v11/tiles/256/2/1/1?access_token=good")):
        r = api.post("/api/mail/packages/map", {"provider": provider, "key": "good"})
        assert r.status_code == 200 and r.json()["provider"] == provider, r.content
        api.get("/api/mail/maptiles/light/2/1/1.png")
        assert seen[-1].endswith(frag), seen[-1]
    # Esri needs no key and has its own dark style (and x/y the other way round).
    assert api.post("/api/mail/packages/map", {"provider": "esri"}).json()["tone"] is False
    api.get("/api/mail/maptiles/dark/2/1/3.png")
    assert seen[-1].endswith("Canvas/World_Dark_Gray_Base/MapServer/tile/2/3/1")
    # Your own server: https only, a public host, {z}/{x}/{y} in it.
    bad = api.post("/api/mail/packages/map", {"provider": "custom", "custom": {"light": "http://tiles.example.com/{z}/{x}/{y}.png"}})
    assert bad.status_code == 400
    monkeypatch.setattr(geo, "_check_template", lambda u: u.strip())
    ok = api.post("/api/mail/packages/map", {"provider": "custom", "custom": {"light": "https://tiles.example.com/{z}/{x}/{y}.png", "attribution": "Mine"}})
    assert ok.json()["provider"] == "custom" and ok.json()["attribution"] == "Mine"
    api.get("/api/mail/maptiles/dark/2/1/1.png")
    assert seen[-1] == "https://tiles.example.com/2/1/1.png"


# --- TrackingMore --------------------------------------------------------------------------


@pytest.fixture
def tm(monkeypatch):
    calls, answers = [], {}

    def call(key, method, path, body=None):
        calls.append((key, method, path, body))
        hit = answers.get((method, path.split("?")[0]))
        if isinstance(hit, Exception):
            raise hit
        return hit if hit is not None else {"meta": {"code": 200}, "data": []}

    monkeypatch.setattr(tm_mod, "_call", call)
    return calls, answers


TM_ITEM = {"tracking_number": USPS, "courier_code": "usps", "delivery_status": "transit",
           "origin_info": {"trackinfo": [
               {"checkpoint_date": "2026-11-20T07:15:00-06:00", "tracking_detail": "Out for Delivery", "location": "Austin, TX, United States"},
               {"checkpoint_date": "2026-11-17T14:30:00-07:00", "tracking_detail": "Accepted", "location": "Portland, OR, United States"}]}}


def test_trackingmore_creates_once_then_reads(ship, tm):
    calls, answers = tm
    tracking.configure("trackingmore", "TMKEY")
    assert tracking.allowance()["limit"] == 50
    answers[("POST", "/trackings/create")] = {"meta": {"code": 200}, "data": TM_ITEM}
    assert tracking.refresh() == 1
    ship.refresh_from_db()
    assert ship.status == "out_for_delivery" and ship.location == "Austin, TX, United States"
    assert calls[0][1:] == ("POST", "/trackings/create", {"tracking_number": USPS, "courier_code": "usps"})
    assert tracking.allowance()["used"] == 1
    # Next time: a free read, not another credit.
    Shipment.objects.update(checked_at=None)
    calls.clear()
    answers[("GET", "/trackings/get")] = {"meta": {"code": 200}, "data": [{**TM_ITEM, "delivery_status": "delivered"}]}
    tracking.refresh()
    assert [c[1:3] for c in calls] == [("GET", "/trackings/get?tracking_numbers=9400111202555842332669&courier_code=usps")]
    ship.refresh_from_db()
    assert ship.status == "delivered"


def test_trackingmore_detects_unknown_carriers(db, tm):
    calls, answers = tm
    Shipment.objects.create(carrier="dhl", number="1234567890", status="in_transit", status_at=timezone.now())
    tracking.configure("trackingmore", "TMKEY")
    answers[("POST", "/couriers/detect")] = {"meta": {"code": 200}, "data": [{"courier_code": "dhl"}]}
    answers[("POST", "/trackings/create")] = {"meta": {"code": 200}, "data": {**TM_ITEM, "tracking_number": "1234567890"}}
    tracking.refresh()
    assert [c[2] for c in calls] == ["/couriers/detect", "/trackings/create"]
    assert calls[1][3]["courier_code"] == "dhl"


def test_trackingmore_errors(ship, tm):
    _, answers = tm
    tracking.configure("trackingmore", "TMKEY")
    answers[("POST", "/trackings/create")] = tm_mod._error(401, {"meta": {"code": 401, "message": "Unauthorized"}})
    tracking.refresh()
    assert tracking.settings_json()["lastError"] == "TrackingMore refused the API key."


# --- Universal Parcel Scraper ------------------------------------------------------------------

SCRAPED = {"carrier": "usps", "source": "usps", "attempts": [], "result": {
    "current_stage": "out_for_delivery", "expected_delivery": "2026-11-20",
    "events": [
        {"time": "2026-11-20T07:15:00-06:00", "instant": "2026-11-20T13:15:00Z", "description": "Out for Delivery",
         "location": "Austin, TX, United States", "stage": "out_for_delivery", "stage_source": "map"},
        {"time": "2026-11-17T14:30:00", "instant": None, "description": "Accepted at USPS Origin Facility",
         "location": "Portland, OR, United States", "stage": "accepted", "stage_source": "map"}]}}


def test_scraper_built_in(ship, monkeypatch):
    import json
    import subprocess

    ran = []

    class Done:
        returncode = 0
        stdout = json.dumps(SCRAPED).encode()
        stderr = b""

    def run(cmd, **kw):
        ran.append((cmd, kw["env"]))
        return Done()

    monkeypatch.setattr(scraper_mod, "binary", lambda: "/opt/parcel-scraper/bin/parcel-scraper")
    monkeypatch.setattr(subprocess, "run", run)
    out = tracking.configure("scraper", scraper={"fallbacks": ["UPU", "17TRACK", "nonsense"]})
    assert out["hasKey"] and out["allowance"] is None and out["scraper"]["builtIn"]
    assert tracking.refresh() == 1
    cmd, env = ran[0]
    assert cmd == ["/opt/parcel-scraper/bin/parcel-scraper", "track", USPS, "--carrier", "usps"]
    assert env["SCRAPER_PROVIDERS"] == "UPU,17TRACK" and "Kern" in env["SCRAPER_USER_AGENT"]
    ship.refresh_from_db()
    assert ship.status == "out_for_delivery" and len(ship.route["points"]) == 2
    assert ship.live_events[0]["at"] == "2026-11-20T07:15:00-06:00"


def test_scraper_without_a_copy(ship, monkeypatch):
    monkeypatch.setattr(scraper_mod, "binary", lambda: "")
    tracking.configure("scraper")
    assert not tracking.enabled()
    assert tracking.refresh() == 0
    with pytest.raises(tracking.TrackingError):
        tracking.check_key()


def test_scraper_your_own_server(ship, monkeypatch):
    seen = []
    monkeypatch.setattr(scraper_mod, "binary", lambda: "")
    monkeypatch.setattr(scraper_mod.Scraper, "http_json",
                        staticmethod(lambda url, **kw: seen.append((url, kw.get("body"), kw.get("headers"))) or SCRAPED))
    from mail import hosts

    with pytest.raises(tracking.TrackingError):  # private addresses need the administrator's OK
        tracking.configure("scraper", scraper={"url": "http://127.0.0.1:8080"})
    monkeypatch.setattr(hosts, "check", lambda h, p: None)
    with pytest.raises(tracking.TrackingError):
        tracking.configure("scraper", scraper={"url": "ftp://parcels.example.com"})
    tracking.configure("scraper", key="tok", scraper={"url": "https://parcels.example.com/"})
    assert tracking.refresh() == 1
    url, payload, headers = seen[0]
    assert url == "https://parcels.example.com/v1/track"
    assert payload == {"number": USPS, "carrier": "usps"} and headers == {"Authorization": "Bearer tok"}


def test_old_parcels_settings_still_work(db):
    from kern import secretbox
    from mail.models import Preferences

    Preferences.objects.update_or_create(pk=1, defaults={"data": {"tracking": {
        "provider": "parcels", "key_enc": secretbox.encrypt("OLD"), "limit": 120,
        "sent": {"month": timezone.localdate().strftime("%Y-%m"), "numbers": ["A"]}}}})
    assert tracking.secret("parcels") == "OLD"
    a = tracking.allowance()
    assert a["limit"] == 120 and a["used"] == 1


def test_saving_settings_does_no_lookups(api, ship, fake):
    """Turning tracking on only checks the service; the worker does the lookups right after."""
    calls, _ = fake
    r = api.post("/api/mail/packages/tracking", {"provider": "parcels", "key": "KEY"})
    assert r.status_code == 200
    assert [c[2].split("?")[0] for c in calls] == ["/tracking-carriers"]  # the key check only
    assert tracking.kicked()
    tracking.refresh()  # what the worker runs within seconds
    assert any(c[2] == "/trackings" for c in calls)
    assert not tracking.kicked()


def test_a_round_stops_starting_lookups_after_its_time(db, monkeypatch):
    import json
    import subprocess

    for i in range(3):
        Shipment.objects.create(carrier="ups", number=f"1Z{i}", status="in_transit", status_at=timezone.now())
    clock = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])

    class Done:
        returncode = 0
        stdout = json.dumps(SCRAPED).encode()
        stderr = b""

    def run(cmd, **kw):
        clock[0] += 70  # each carrier takes 70 s
        return Done()

    monkeypatch.setattr(scraper_mod, "binary", lambda: "/usr/bin/parcel-scraper")
    monkeypatch.setattr(subprocess, "run", run)
    tracking.configure("scraper")
    tracking.refresh()
    checked = set(Shipment.objects.filter(checked_at__isnull=False).values_list("number", flat=True))
    assert checked == {"1Z0", "1Z1"}  # 140 s: the third waits for the next round, first in line


def test_scraper_says_why_it_found_nothing(ship, monkeypatch):
    import json
    import subprocess

    class Failed:
        returncode = 1
        stdout = b""
        stderr = json.dumps({"error": "No history", "attempts": [{"source": "usps", "kind": "challenge", "durationMs": 900}],
                             "hint": {"kind": "challenge"}}).encode()

    monkeypatch.setattr(scraper_mod, "binary", lambda: "/usr/bin/parcel-scraper")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: Failed())
    tracking.configure("scraper")
    assert tracking.refresh() == 0
    ship.refresh_from_db()
    assert ship.status == "in_transit"  # unchanged
    assert ship.track_note.startswith("USPS only answers a real browser")
    assert scraper_mod.failure_note({"error": "USPS challenged direct tracking; configure FLARESOLVERR_URL for browser fallback",
                                     "hint": {"kind": "challenge"}}, "USPS").startswith("USPS can only be read through the scraper's browser service")
    assert "No package was found" in tracking.settings_json()["lastError"]
    # Shown with the package, and cleared once a lookup works.
    assert api_json_note(ship) == ship.track_note

    class Done:
        returncode = 0
        stdout = json.dumps(SCRAPED).encode()
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: Done())
    Shipment.objects.update(checked_at=None)
    tracking.refresh()
    ship.refresh_from_db()
    assert ship.track_note == "" and ship.status == "out_for_delivery"


def api_json_note(s):
    from mail.api.views import shipment_json

    return shipment_json(s)["trackNote"]


def test_amazon_is_not_looked_up(db, monkeypatch):
    import subprocess

    s = Shipment.objects.create(carrier="amazon", number="TBA312345678901", status="in_transit", status_at=timezone.now())
    ran = []
    monkeypatch.setattr(scraper_mod, "binary", lambda: "/usr/bin/parcel-scraper")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    tracking.configure("scraper")
    tracking.refresh()
    s.refresh_from_db()
    assert ran == [] and "Amazon account" in s.track_note


def test_browser_is_passed_only_when_there(ship, monkeypatch, tmp_path):
    import json
    import subprocess

    seen = []

    class Done:
        returncode = 0
        stdout = json.dumps(SCRAPED).encode()
        stderr = b""

    monkeypatch.setattr(scraper_mod, "binary", lambda: "/usr/bin/parcel-scraper")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(kw["env"]) or Done())
    monkeypatch.setenv("TRACKING_CHROMIUM_PATH", str(tmp_path / "nope"))
    tracking.configure("scraper")
    tracking.refresh()
    assert "TRACKING_CHROMIUM_PATH" not in seen[-1]
    chromium = tmp_path / "chromium"
    chromium.write_text("")
    monkeypatch.setenv("TRACKING_CHROMIUM_PATH", str(chromium))
    Shipment.objects.update(checked_at=None, status="in_transit")
    tracking.refresh()
    assert seen[-1]["TRACKING_CHROMIUM_PATH"] == str(chromium)
