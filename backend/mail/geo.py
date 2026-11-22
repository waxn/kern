"""Where a package is: scan locations on a map.

* Places: a carrier's scan location ("Malmö, Sweden", "AUSTIN, TX, United States") is looked up
  once with OpenStreetMap's Nominatim and kept in GeoPlace. Only the place name is sent, never
  anything from your mail, at most one lookup a second (Nominatim's usage policy).
* Map tiles, fetched by the server and cached on disk, so the browser and the phone only ever
  talk to Kern (your IP address isn't sent to the map provider). Sources (MAP_SOURCES, picked in
  Settings → Mail → Package map): OpenStreetMap (no key; toned down by the apps), Esri's grey
  canvas (no key; dark and light), MapTiler, Stadia Maps, Thunderforest and Mapbox (free keys;
  dark and light styles), or your own tile server.

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
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from .models import GeoPlace

log = logging.getLogger(__name__)

UA = "Kern-Mail/1 (self-hosted mail client; package map)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
THEMES = ("dark", "light")
TILES_REV = 2  # bump to make every app fetch tiles afresh
TILE_MAX_AGE = 30 * 86400


@dataclass(frozen=True)
class MapSource:
    """A tile service. url has {z} {x} {y}, {style} (from styles, per theme) and {key}."""

    name: str
    url: str
    attribution: str
    styles: dict = field(default_factory=lambda: {"dark": "", "light": ""})
    needs_key: bool = False
    tone: bool = False  # one colourful style for both themes: the apps grey it down (dark: inverted)
    signup: str = ""


MAP_SOURCES = {
    "osm": MapSource("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors",
                     tone=True),
    "esri": MapSource("Esri grey canvas", "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/{style}/MapServer/tile/{z}/{y}/{x}",
                      "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors",
                      {"dark": "World_Dark_Gray_Base", "light": "World_Light_Gray_Base"}),
    "maptiler": MapSource("MapTiler", "https://api.maptiler.com/maps/{style}/256/{z}/{x}/{y}.png?key={key}",
                          "© MapTiler © OpenStreetMap contributors", {"dark": "dataviz-dark", "light": "dataviz"},
                          needs_key=True, signup="https://cloud.maptiler.com/account/keys/"),
    "stadia": MapSource("Stadia Maps", "https://tiles.stadiamaps.com/tiles/{style}/{z}/{x}/{y}.png?api_key={key}",
                        "© Stadia Maps © OpenMapTiles © OpenStreetMap contributors",
                        {"dark": "alidade_smooth_dark", "light": "alidade_smooth"}, needs_key=True,
                        signup="https://client.stadiamaps.com/signup/"),
    "thunderforest": MapSource("Thunderforest", "https://tile.thunderforest.com/{style}/{z}/{x}/{y}.png?apikey={key}",
                               "Maps © Thunderforest, Data © OpenStreetMap contributors",
                               {"dark": "transport-dark", "light": "atlas"}, needs_key=True,
                               signup="https://manage.thunderforest.com/users/sign_up"),
    "mapbox": MapSource("Mapbox", "https://api.mapbox.com/styles/v1/mapbox/{style}/tiles/256/{z}/{x}/{y}?access_token={key}",
                        "© Mapbox © OpenStreetMap contributors", {"dark": "dark-v11", "light": "light-v11"},
                        needs_key=True, signup="https://account.mapbox.com/access-tokens/"),
    "custom": MapSource("Your own tile server", "", "", {"dark": "", "light": ""}),
}

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
    m = dict(((row.data if row else None) or {}).get("map") or {})
    if m.get("key_enc"):  # saved before there was a choice: a MapTiler key
        m = {"provider": "maptiler", "keys": {"maptiler": m["key_enc"]}}
    return m


def _secret(m: dict, name: str) -> str:
    from kern import secretbox

    enc = (m.get("keys") or {}).get(name)
    if not enc:
        return ""
    try:
        return secretbox.decrypt(enc)
    except Exception:  # noqa: BLE001 - a key saved on another server can't be read here
        return ""


def _active(m: dict | None = None) -> tuple[str, dict]:
    """(source name, its settings) in use; OpenStreetMap when the chosen one isn't usable."""
    m = _map_cfg() if m is None else m
    name = m.get("provider") or "osm"
    src = MAP_SOURCES.get(name)
    if src is None or (src.needs_key and not _secret(m, name)) or (name == "custom" and not (m.get("custom") or {}).get("light")):
        return "osm", m
    return name, m


def map_json() -> dict:
    """What the apps need to draw the map: whose tiles, the credit line, whether to tone them."""
    m = _map_cfg()
    name, _ = _active(m)
    src = MAP_SOURCES[name]
    custom = m.get("custom") or {}
    attribution = (custom.get("attribution") or "Map tiles: your server") if name == "custom" else src.attribution
    import hashlib

    # In the tile addresses (?v=…), so a browser or phone that cached another source's tiles
    # doesn't keep showing them after a switch.
    version = hashlib.sha256(f"{name}|{custom.get('light', '')}|{custom.get('dark', '')}|{TILES_REV}".encode()).hexdigest()[:10]
    return {
        "provider": name, "chosen": m.get("provider") or "osm", "attribution": attribution, "tone": src.tone, "version": version,
        "keys": {n: bool(_secret(m, n)) for n, x in MAP_SOURCES.items() if x.needs_key},
        "custom": {"light": custom.get("light", ""), "dark": custom.get("dark", ""), "attribution": custom.get("attribution", "")},
        "sources": [{"id": n, "name": x.name, "needsKey": x.needs_key, "signup": x.signup} for n, x in MAP_SOURCES.items()],
    }


def _url(name: str, m: dict, theme: str, z: int, x: int, y: int) -> str:
    if name == "custom":
        custom = m.get("custom") or {}
        tpl = custom.get(theme) or custom.get("light") or ""
        return tpl.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    src = MAP_SOURCES[name]
    return src.url.format(style=src.styles.get(theme, ""), z=z, x=x, y=y, key=urllib.parse.quote(_secret(m, name)))


def _check_template(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0"))
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or not all(
            p in url for p in ("{z}", "{x}", "{y}")):
        raise ValueError("A tile address looks like https://tiles.example.com/{z}/{x}/{y}.png")
    from . import hosts

    try:
        hosts.check(parts.hostname, parts.port or 443)
    except hosts.HostNotAllowed as exc:
        raise ValueError(str(exc)) from exc
    return url[:500]


def configure_map(provider: str, key: str | None = None, custom: dict | None = None) -> dict:
    """Pick the tile source; a key (or tile address) is tried with one tile before it's saved."""
    from kern import secretbox

    from .models import Preferences

    if provider not in MAP_SOURCES:
        raise ValueError("Unknown map source.")
    m = _map_cfg()
    src = MAP_SOURCES[provider]
    keys = m.setdefault("keys", {})
    if key is not None and src.needs_key:
        key = key.strip()
        if len(key) > 300 or any(c.isspace() for c in key):
            raise ValueError("That doesn't look like a key.")
        if key:
            keys[provider] = secretbox.encrypt(key)
        else:
            keys.pop(provider, None)
    if custom is not None and provider == "custom":
        m["custom"] = {"light": _check_template(str(custom.get("light") or "")),
                       "dark": _check_template(str(custom.get("dark") or "")),
                       "attribution": " ".join(str(custom.get("attribution") or "").split())[:200]}
    if src.needs_key and not _secret(m, provider):
        raise ValueError(f"Paste your {src.name} key.")
    if provider == "custom" and not (m.get("custom") or {}).get("light"):
        raise ValueError("Enter your tile server's address.")
    if provider not in ("osm", "esri"):  # try it before switching
        try:
            _fetch(_url(provider, m, "light", 0, 0, 0))
        except urllib.error.HTTPError as e:
            raise ValueError(f"{src.name} refused the key." if e.code in (401, 403) else f"{src.name} answered {e.code}.") from e
        except OSError as e:
            raise ValueError(f"Couldn't get a map tile from {src.name}.") from e
    m["provider"] = provider
    row, _ = Preferences.objects.get_or_create(pk=1, defaults={"data": {}})
    data = dict(row.data or {})
    data["map"] = m
    row.data = data
    row.save(update_fields=["data", "updated"])
    return map_json()


def set_maptiler_key(key: str | None) -> dict:
    """Kept for the earlier settings call: a key switches to MapTiler, none to OpenStreetMap."""
    return configure_map("maptiler", key) if key else configure_map("osm")


def _fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise OSError("tiles come over https only")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as r:  # noqa: S310
        data = r.read(2_000_000)
    if not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8") or data[8:12] == b"WEBP"):
        raise OSError("not a map tile")
    return data


def image_type(data: bytes) -> str:
    return "image/jpeg" if data.startswith(b"\xff\xd8") else "image/webp" if data[8:12] == b"WEBP" else "image/png"


def _tile_path(source: str, z: int, x: int, y: int) -> Path:
    return Path(settings.DATA_DIR) / "cache" / "maptiles" / source / str(z) / str(x) / f"{y}.img"


def tile(theme: str, z: int, x: int, y: int) -> bytes:
    """A 256 px map tile (PNG, JPEG or WebP; the apps draw one zoom level deeper at half size for
    sharp screens). Raises ValueError for a bad address, OSError when unavailable."""
    if theme not in THEMES or not 0 <= z <= 18 or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("No such tile.")
    name, m = _active()
    src = MAP_SOURCES[name]
    if name == "custom":
        import hashlib

        template = (m.get("custom") or {}).get(theme) or (m.get("custom") or {}).get("light")
        _check_template(template)  # again: DNS may have changed
        source = "custom-" + hashlib.sha256(template.encode()).hexdigest()[:12]
    else:
        source = name + ("-" + src.styles.get(theme, "") if src.styles.get(theme) else "")
    path = _tile_path(source, z, x, y)
    try:
        if time.time() - path.stat().st_mtime < TILE_MAX_AGE:
            return path.read_bytes()
    except OSError:
        pass
    data = _fetch(_url(name, m, theme, z, x, y))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data
