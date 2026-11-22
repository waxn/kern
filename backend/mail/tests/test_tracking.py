"""Live package tracking with Parcels (mail/tracking.py), the service and the map faked."""

from datetime import timedelta

import pytest
from django.utils import timezone

from mail import geo, tracking
from mail.models import ChangeEvent, GeoPlace, Shipment

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
    monkeypatch.setattr(tracking, "POLL_WAIT", 0)


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

    monkeypatch.setattr(tracking, "_call", call)
    return calls, answers


def test_off_without_a_key(ship, fake):
    calls, _ = fake
    assert not tracking.enabled()
    assert tracking.refresh() == 0
    assert calls == []


def test_key_is_stored_encrypted(db):
    out = tracking.configure("parcels", "PK_live_123", country="se")
    assert out["provider"] == "parcels" and out["hasKey"] and out["country"] == "SE"
    assert out["allowance"] == {"limit": 300, "used": 0, "left": 300, "month": timezone.localdate().strftime("%Y-%m"), "exact": False}
    from mail.models import Preferences

    assert "PK_live_123" not in str(Preferences.objects.get(pk=1).data)
    assert tracking._key() == "PK_live_123"
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
    # Numbers already counted this cycle stay free to ask about again.
    Shipment.objects.update(checked_at=None)
    calls.clear()
    tracking.refresh()
    assert {i["tracking_number"] for i in calls[0][3]["shipments"]} == {"1Z0", "1Z1"}


def test_exact_quota_from_parcels(ship, fake):
    _, answers = fake
    tracking.configure("parcels", "KEY")
    err = tracking._error(402, {"code": "SUBSCRIPTION_LIMIT_REACHED", "limit": 300, "current": 299, "available": 1})
    answers[("POST", "/trackings")] = err
    assert tracking.refresh() == 0
    a = tracking.allowance()
    assert a["exact"] and a["used"] == 299 and a["left"] == 1
    assert "used up" in tracking.settings_json()["lastError"]


def test_bad_key(ship, fake):
    _, answers = fake
    tracking.configure("parcels", "KEY")
    answers[("POST", "/trackings")] = tracking._error(401, {"code": "INVALID_API_KEY", "message": "x"})
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
    assert api.get("/api/mail/packages/map").json()["provider"] == "osm"
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
