"""Tracking services for live package tracking (mail/tracking.py has the shared part).

Each module has a class with the same few things: ``LABEL``, ``NEEDS_KEY``, ``METERED`` (counts
new packages against a monthly allowance), ``FREE_LIMIT``, ``available(cfg)``, ``check(cfg)`` and
``lookup(shipments, cfg) -> ({number: Result}, warning)``.
"""

from .parcels import Parcels
from .scraper import Scraper
from .trackingmore import TrackingMore

TRACKERS = {"parcels": Parcels, "trackingmore": TrackingMore, "scraper": Scraper}
