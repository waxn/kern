"""Package tracking from shipping emails. Rules only, runs locally.

Finds tracking numbers in emails that look like shipping notices, works out
the carrier, and reads the delivery status from the wording ("shipped",
"out for delivery", "delivered", in several languages). Nothing is sent to
carriers automatically: Manifest only builds a link to the carrier's own
tracking page, which opens when *you* click it.

False positives are kept down by validating check digits wherever the
number format has one (UPS 1Z, UPU S10 postal numbers, USPS, FedEx, DHL),
and by requiring the carrier to be named for formats that are just digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# --- check digits ------------------------------------------------------------


def ups_valid(n: str) -> bool:
    """1Z + 6 shipper + 2 service + 7 package + 1 check digit."""
    n = n.upper()
    if not re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return False
    body = n[2:17]
    total = 0
    for i, ch in enumerate(body):
        v = int(ch) if ch.isdigit() else (ord(ch) - 63) % 10
        total += v * 2 if i % 2 else v
    return (10 - total % 10) % 10 == int(n[17]) if n[17].isdigit() else False


def s10_valid(n: str) -> bool:
    """UPU S10: two letters, 8 digits, check digit, two-letter country."""
    n = n.upper()
    if not re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", n):
        return False
    digits = [int(c) for c in n[2:10]]
    s = sum(d * w for d, w in zip(digits, (8, 6, 4, 2, 3, 5, 9, 7)))
    check = 11 - s % 11
    check = {10: 0, 11: 5}.get(check, check)
    return check == int(n[10])


def mod10_31_valid(n: str) -> bool:
    """USPS 20/22-digit (and similar): weights 3,1 from the right, mod 10."""
    if not n.isdigit() or len(n) < 12:
        return False
    body, check = n[:-1], int(n[-1])
    s = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - s % 10) % 10 == check


def fedex12_valid(n: str) -> bool:
    if not re.fullmatch(r"\d{12}", n):
        return False
    # FedEx Express: weights 3,1,7 repeating, left to right over the first 11 digits.
    s = sum(int(d) * w for d, w in zip(n[:11], [3, 1, 7] * 4))
    return s % 11 % 10 == int(n[11])


def dhl10_valid(n: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", n)) and int(n[:9]) % 7 == int(n[9])


# --- carriers -------------------------------------------------------------------


@dataclass(frozen=True)
class Carrier:
    id: str
    name: str
    url: str  # {n} = tracking number
    domains: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


CARRIERS = {
    c.id: c for c in [
        Carrier("ups", "UPS", "https://www.ups.com/track?tracknum={n}", ("ups.com",), ("ups",)),
        Carrier("fedex", "FedEx", "https://www.fedex.com/fedextrack/?trknbr={n}", ("fedex.com",), ("fedex",)),
        Carrier("usps", "USPS", "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}", ("usps.com", "usps.gov"), ("usps",)),
        Carrier("dhl", "DHL", "https://www.dhl.com/global-en/home/tracking/tracking-express.html?tracking-id={n}",
                ("dhl.com", "dhl.de", "dhl.se"), ("dhl",)),
        Carrier("postnord", "PostNord", "https://www.postnord.se/en/our-tools/track-and-trace?shipmentId={n}",
                ("postnord.com", "postnord.se", "postnord.dk"), ("postnord",)),
        Carrier("royalmail", "Royal Mail", "https://www.royalmail.com/track-your-item#/tracking-results/{n}",
                ("royalmail.com",), ("royal mail",)),
        Carrier("amazon", "Amazon Logistics", "https://track.amazon.com/tracking/{n}", ("amazon.com",), ()),
        Carrier("dpd", "DPD", "https://tracking.dpd.de/status/en_US/parcel/{n}", ("dpd.com", "dpd.de", "dpd.co.uk"), ("dpd",)),
        Carrier("gls", "GLS", "https://gls-group.com/track/{n}", ("gls-group.eu", "gls-group.com"), ("gls",)),
        Carrier("bring", "Bring", "https://tracking.bring.com/tracking/{n}", ("bring.com", "posten.no"), ("bring", "posten")),
        Carrier("post", "Postal service", "", (), ()),
    ]
}

S10_COUNTRY = {"US": "usps", "GB": "royalmail", "SE": "postnord", "DK": "postnord", "NO": "bring", "DE": "dhl"}


def track_url(carrier_id: str, number: str) -> str:
    c = CARRIERS.get(carrier_id)
    return c.url.format(n=number) if c and c.url else ""


# --- detection ------------------------------------------------------------------

SHIPPING_WORDS = re.compile(
    r"\b(track(ing)?|shipment|shipped|shipping|delivery|delivered|package|parcel|dispatched|courier|"
    r"out for delivery|in transit|order|sendung|paket|zugestellt|sendungsnummer|försändelse|paket|kolli|"
    r"leverans|levererad|spårning|colis|livraison|pakke|sending)\b",
    re.IGNORECASE,
)

STATUS_ORDER = ["ordered", "shipped", "in_transit", "out_for_delivery", "ready_for_pickup", "exception", "delivered"]
# Progress bar position: label created -> on the way -> nearly there -> delivered.
STATUS_STEP = {"ordered": 0, "shipped": 1, "in_transit": 1, "exception": 1, "out_for_delivery": 2,
               "ready_for_pickup": 2, "delivered": 3}
STATUS_LABEL = {
    "ordered": "Label created",
    "shipped": "Shipped",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "ready_for_pickup": "Ready for pickup",
    "exception": "Needs attention",
    "delivered": "Delivered",
}
# Checked in this order; the first match wins (most final states first).
STATUS_PATTERNS = [
    # "will be delivered", "to be delivered by", "wird heute zugestellt" are promises, not deliveries.
    ("delivered", r"(?<!be )(?<!wird )(?<!heute )\b(delivered|zugestellt|levererad|har levererats|livré|levert)\b"
                  r"(?! (by|on|between|tomorrow|today|to you (today|tomorrow)))"),
    ("ready_for_pickup", r"(ready (for|to be) (pick ?up|collect)|ready to collect|kan hämtas|available for pickup|abholbereit|"
                         r"at (the|your) pick ?up point)"),
    ("exception", r"(delivery attempt|attempted delivery|missed delivery|failed delivery|could not be delivered|"
                  r"delivery exception|delayed|returned to sender|address issue|zustellversuch)"),
    ("out_for_delivery", r"(out for delivery|on (its|the) way to you today|arriving today|ute för leverans|"
                         r"in zustellung|wird heute zugestellt|en cours de livraison)"),
    ("in_transit", r"(in transit|on (its|the) way|has (been )?shipped|was shipped|shipped|dispatched|has left|"
                   r"is on its way|skickad|har skickats|unterwegs|versandt|expédié)"),
    ("ordered", r"(label (has been )?created|shipping label|order (confirmed|received)|preparing (your|for) shipment|"
                r"we('| a)re getting your order ready)"),
]

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
EXPECTED = re.compile(
    r"(?:expected|estimated|scheduled|arriv(?:es|ing)|delivery (?:date|by)|deliver(?:ed)? by|will arrive|beräknad leverans|"
    r"voraussichtlich)\s*(?:delivery)?\s*(?:date)?\s*[:\-]?\s*(?:on\s+|by\s+)?"
    r"(?P<what>today|tomorrow|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*(?:,?\s+\w+\s+\d{1,2})?|"
    r"\w+\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}\s+\w+|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


@dataclass
class Found:
    number: str
    carrier: str
    status: str
    expected: date | None = None
    expected_text: str = ""


@dataclass
class Scan:
    packages: list[Found] = field(default_factory=list)


def _carrier_named(carrier_id: str, sender_domain: str, text_low: str) -> bool:
    c = CARRIERS[carrier_id]
    if any(sender_domain == d or sender_domain.endswith("." + d) for d in c.domains):
        return True
    return any(re.search(rf"\b{re.escape(n)}\b", text_low) for n in c.names)


def find_numbers(text: str, sender_domain: str = "") -> list[tuple[str, str]]:
    """[(number, carrier_id)] in order of appearance, de-duplicated."""
    low = text.lower()
    out: list[tuple[str, str]] = []
    seen = set()

    def add(n, c):
        if n not in seen:
            seen.add(n)
            out.append((n, c))

    for m in re.finditer(r"\b1Z[0-9A-Z]{16}\b", text, re.IGNORECASE):
        if ups_valid(m.group(0)):
            add(m.group(0).upper(), "ups")
    for m in re.finditer(r"\bTBA\d{12}\b", text):
        add(m.group(0), "amazon")
    for m in re.finditer(r"\b[A-Z]{2}\d{9}[A-Z]{2}\b", text):
        n = m.group(0)
        if s10_valid(n):
            add(n, S10_COUNTRY.get(n[-2:], "post"))
    for m in re.finditer(r"\b(9[2-5]\d{18,20}|420\d{5}9[2-5]\d{18,20})\b", text):
        n = m.group(1)[-22:] if m.group(1).startswith("420") else m.group(1)
        if mod10_31_valid(n):
            add(n, "usps")
    for m in re.finditer(r"\bJJD\d{18}\b", text):
        add(m.group(0), "dhl")
    # Digit-only formats: the carrier must be named in the email (or be the
    # sender) AND the digits must follow a tracking word, so order, invoice
    # and phone numbers are left alone (1 in 10 random numbers pass a check digit).
    ctx = re.compile(r"(track|tracking|sendung|parcel|paket|kolli|shipment|försändelse|sending|waybill|awb)[^\n]{0,40}$", re.I)
    for cid, pattern, valid in (
        ("fedex", r"(?<!\d)(\d{12})(?!\d)", fedex12_valid),
        ("dhl", r"(?<!\d)(\d{10})(?!\d)", dhl10_valid),
        ("dpd", r"(?<!\d)(\d{14})(?!\d)", None),
        ("gls", r"(?<!\d)(\d{11,12})(?!\d)", None),
        ("postnord", r"(?<!\d)(\d{18})(?!\d)", None),
        ("bring", r"(?<![\dA-Z])(\d{17}|[A-Z]{3}\d{10,12})(?![\dA-Z])", None),
    ):
        if not _carrier_named(cid, sender_domain, low):
            continue
        for m in re.finditer(pattern, text):
            if (valid is None or valid(m.group(1))) and ctx.search(text[max(0, m.start() - 50):m.start()]):
                add(m.group(1), cid)
    return out


def detect_status(subject: str, text: str) -> str:
    for source in (subject, text[:4000]):
        low = source.lower()
        for status, pattern in STATUS_PATTERNS:
            if re.search(pattern, low):
                return status
    return "in_transit"


def expected_date(text: str, sent: datetime | None) -> tuple[date | None, str]:
    m = EXPECTED.search(text[:6000])
    if not m:
        return None, ""
    what = m.group("what").strip().rstrip(".,")
    base = (sent or datetime.now()).date()
    low = what.lower()
    if low == "today":
        return base, "Today"
    if low == "tomorrow":
        return base + timedelta(days=1), "Tomorrow"
    try:
        return date.fromisoformat(what), what
    except ValueError:
        pass
    words = re.findall(r"[a-z]+|\d+", low)
    day = next((int(w) for w in words if w.isdigit() and 1 <= int(w) <= 31), None)
    month = next((MONTHS.index(m2) + 1 for w in words for m2 in MONTHS if len(w) >= 3 and m2.startswith(w)), None)
    if day and month:
        year = base.year + (1 if month < base.month - 6 else 0)
        try:
            return date(year, month, day), what
        except ValueError:
            return None, what
    wd = next((i for w in words for i, d in enumerate(WEEKDAYS) if len(w) >= 3 and d.startswith(w)), None)
    if wd is not None:
        ahead = (wd - base.weekday()) % 7
        return base + timedelta(days=ahead), what.title()
    return None, ""


def scan(subject: str, text: str, sender_addr: str, sent: datetime | None) -> Scan:
    blob = f"{subject}\n{text}"
    if not SHIPPING_WORDS.search(blob[:20000]):
        return Scan()
    domain = sender_addr.rpartition("@")[2].lower()
    numbers = find_numbers(blob[:50000], domain)
    if not numbers:
        return Scan()
    status = detect_status(subject, text)
    exp, exp_text = expected_date(blob, sent)
    return Scan([Found(n, c, status, exp if status != "delivered" else None, exp_text if status != "delivered" else "")
                 for n, c in numbers[:5]])
