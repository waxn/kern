"""Where a package is: scan locations on a map.

* Places: a carrier's scan location ("Malmö, Sweden", "AUSTIN, TX, United States") is looked up
  once with OpenStreetMap's Nominatim and kept in GeoPlace. Only the place name is sent, never
  anything from your mail, at most one lookup a second (Nominatim's usage policy).
* Map tiles, fetched by the server and cached on disk, so the browser and the phone only ever
  talk to Kern (your IP address isn't sent to the map provider):
  - with a MapTiler key (Settings → Mail → Package tracking, free plan): MapTiler's muted
    "dataviz" maps, a dark one and a light one to match Kern's theme;
  - without one: OpenStreetMap's own tiles (no key; light use and caching are what its tile
    policy asks for), which the apps tone down to the theme.

SECURITY: both fetch fixed https hosts only; nothing from the request picks a host.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings

from .models import GeoPlace

log = logging.getLogger(__name__)

UA = "Kern-Mail/1 (self-hosted mail client; package map)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAPTILER_URL = "https://api.maptiler.com/maps/{style}/256/{z}/{x}/{y}.png?key={key}"
MAPTILER_STYLES = {"dark": "dataviz-dark", "light": "dataviz"}
THEMES = ("dark", "light")
TILE_MAX_AGE = 30 * 86400

_lock = threading.Lock()
_last_lookup = 0.0


def clean_place(name: str) -> str:
    name = " ".join((name or "").replace("\n", " ").split()).strip(" ,-")
    # Facility codes and postcodes carry no place: "SE-21119 Malmö" → "Malmö"; keep it readable.
    name = re.sub(r"\b[A-Z]{2}-?\d{4,6}\b", "", name).strip(" ,-")
    return name[:200]


def lookup(name: str, *, budget: list[int] | None = None) -> tuple[float, float] | None:
    """(lat, lon) for a place name, from the cache or Nominatim. budget=[n] caps new lookups."""
    global _last_lookup
    place = clean_place(name)
    if len(place) < 2:
        return None
    hit = GeoPlace.objects.filter(name=place).first()
    if hit:
        return (hit.lat, hit.lon) if hit.lat is not None else None
    if budget is not None:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_lookup)
        if wait > 0:
            time.sleep(wait)
        _last_lookup = time.monotonic()
        url = NOMINATIM + "?" + urllib.parse.urlencode({"q": place, "format": "jsonv2", "limit": 1})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed https host
                found = json.loads(r.read(200_000))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            log.info("geocoding %r failed: %s", place, e)
            return None  # not cached: try again another time
    lat = lon = None
    if found:
        try:
            lat, lon = float(found[0]["lat"]), float(found[0]["lon"])
        except (KeyError, TypeError, ValueError):
            pass
    GeoPlace.objects.update_or_create(name=place, defaults={"lat": lat, "lon": lon})
    return (lat, lon) if lat is not None else None


def route_points(places_oldest_first: list[str], budget: int = 6) -> list[list]:
    """[[lat, lon, place], ...] for the distinct places in order (repeats collapsed)."""
    b = [budget]
    out: list[list] = []
    for name in places_oldest_first:
        place = clean_place(name)
        if not place or (out and out[-1][2] == place):
            continue
        p = lookup(place, budget=b)
        if p and not (out and abs(out[-1][0] - p[0]) < 1e-4 and abs(out[-1][1] - p[1]) < 1e-4):
            out.append([round(p[0], 5), round(p[1], 5), place])
    return out[-20:]


# --- tiles ------------------------------------------------------------------------------


def _map_cfg() -> dict:
    from .models import Preferences

    row = Preferences.objects.filter(pk=1).first()
    return dict(((row.data if row else None) or {}).get("map") or {})


def _maptiler_key() -> str:
    from kern import secretbox

    enc = _map_cfg().get("key_enc")
    if not enc:
        return ""
    try:
        return secretbox.decrypt(enc)
    except Exception:  # noqa: BLE001 - a key saved on another server can't be read here
        return ""


def map_json() -> dict:
    """What the apps need to draw the map: whose tiles, and the credit line they must show."""
    if _maptiler_key():
        return {"provider": "maptiler", "attribution": "© MapTiler © OpenStreetMap contributors"}
    return {"provider": "osm", "attribution": "© OpenStreetMap contributors"}


def set_maptiler_key(key: str | None) -> dict:
    """Save (after trying it) or forget the MapTiler key."""
    from kern import secretbox

    from .models import Preferences

    row, _ = Preferences.objects.get_or_create(pk=1, defaults={"data": {}})
    data = dict(row.data or {})
    if key:
        key = key.strip()
        if len(key) > 200 or any(c.isspace() for c in key):
            raise ValueError("That doesn't look like a MapTiler key.")
        url = MAPTILER_URL.format(style=MAPTILER_STYLES["dark"], z=0, x=0, y=0, key=urllib.parse.quote(key))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as r:  # noqa: S310
                r.read(1)
        except urllib.error.HTTPError as e:
            raise ValueError("MapTiler refused the key." if e.code in (401, 403) else f"MapTiler answered {e.code}.") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ValueError("Couldn't reach MapTiler.") from e
        data["map"] = {"key_enc": secretbox.encrypt(key)}
    else:
        data.pop("map", None)
    row.data = data
    row.save(update_fields=["data", "updated"])
    return map_json()


def _tile_path(source: str, z: int, x: int, y: int) -> Path:
    return Path(settings.DATA_DIR) / "cache" / "maptiles" / source / str(z) / str(x) / f"{y}.png"


def tile(theme: str, z: int, x: int, y: int) -> bytes:
    """A 256 px map tile (PNG; the apps draw one zoom level deeper at half size for sharp
    screens). Raises ValueError for a bad address, OSError when unavailable."""
    if theme not in THEMES or not 0 <= z <= 18 or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("No such tile.")
    key = _maptiler_key()
    if key:
        source = "maptiler-" + MAPTILER_STYLES[theme]
        url = MAPTILER_URL.format(style=MAPTILER_STYLES[theme], z=z, x=x, y=y, key=urllib.parse.quote(key))
    else:
        source = "osm"  # one style for both themes; the apps tone it down
        url = OSM_URL.format(z=z, x=x, y=y)
    path = _tile_path(source, z, x, y)
    try:
        if time.time() - path.stat().st_mtime < TILE_MAX_AGE:
            return path.read_bytes()
    except OSError:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - fixed https host
        data = r.read(2_000_000)
    if not data.startswith(b"\x89PNG"):
        raise OSError("not a map tile")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data
