"""Phishing risk rules. Plain metadata/header rules; no AI, no body analysis
beyond extracting link targets and attachment names.

Each rule is a function taking a RiskInput and returning None (didn't fire)
or a short human-readable reason. The rule's id (function name) and its
weight come from rules.yaml, where you can tune or disable each one. Scores
add up; rules.yaml also sets the medium/high thresholds.

To add a rule: write a function here decorated with @rule, add it to
rules.yaml with a weight, then rescore existing mail with:
    docker compose run --rm app python manage.py reprocess --stage risk
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .domains import contains_token, looks_like, org_domain, org_label, skeleton, to_ascii, to_unicode

RULES: dict[str, dict] = {}


def rule(title: str, *, history: bool = False):
    """history=True: needs your mail history (skipped during the first sync,
    when that history isn't complete yet)."""

    def deco(fn):
        RULES[fn.__name__] = {"fn": fn, "title": title, "doc": (fn.__doc__ or "").strip(), "history": history}
        return fn

    return deco


@dataclass
class RiskInput:
    from_addr: str
    from_name: str
    reply_to: list[str]
    return_path: str
    auth: dict
    links: list[tuple[str, str]]
    attachment_names: list[str]
    brands: list[dict]
    # Correspondent history for the From address (before this message).
    known_sender: bool = False
    you_wrote_to_sender: bool = False
    # name(casefold) -> set of addresses for people you've written to
    contact_names: dict[str, set[str]] = field(default_factory=dict)
    contact_domains: set[str] = field(default_factory=set)

    @property
    def from_domain(self) -> str:
        return self.from_addr.rpartition("@")[2]

    @property
    def from_org(self) -> str:
        return org_domain(self.from_domain)


def _brand_domains(brand) -> list[str]:
    """Registrable domains of a brand, primary (first listed) first."""
    out: list[str] = []
    for d in brand.get("domains", []):
        od = org_domain(d)
        if od not in out:
            out.append(od)
    return out


def shown(domain: str) -> str:
    """Show a domain so lookalikes can't hide: 'аpple.com (xn--pple-43d.com)'."""
    uni, asc = to_unicode(domain), to_ascii(domain)
    return f"{uni} ({asc})" if uni != asc else uni


# --- Sender authentication ---------------------------------------------------

@rule("DMARC failed")
def dmarc_fail(x: RiskInput):
    """Your provider checked the sender's DMARC policy and it failed: the
    domain in From says this message did not come from them."""
    if x.auth.get("dmarc") == "fail":
        return f"DMARC failed for {x.auth.get('dmarc_from') or x.from_domain}: the domain owner says this message isn't from them."


@rule("SPF failed")
def spf_fail(x: RiskInput):
    """SPF fail: the sending server isn't allowed to send for the envelope domain."""
    if x.auth.get("spf") == "fail":
        return f"SPF failed: the sending server isn't authorized for {x.auth.get('spf_domain') or 'the sender domain'}."


@rule("SPF soft-failed")
def spf_softfail(x: RiskInput):
    """SPF softfail: the domain says the server is probably not authorized."""
    if x.auth.get("spf") == "softfail":
        return "SPF soft-failed: the sending server is probably not authorized."


@rule("DKIM signature failed")
def dkim_fail(x: RiskInput):
    """A DKIM signature was present but didn't verify, and none passed."""
    results = [d["result"] for d in x.auth.get("dkim", [])]
    if "fail" in results and "pass" not in results:
        return "A DKIM signature was present but didn't verify (message may have been altered or forged)."


@rule("Sender not authenticated")
def unauthenticated(x: RiskInput):
    """Your provider checked, but neither SPF nor DKIM passed."""
    if not x.auth.get("trusted"):
        return None
    if x.auth.get("spf") != "pass" and not any(d["result"] == "pass" for d in x.auth.get("dkim", [])):
        return "Neither SPF nor DKIM confirmed who sent this."


@rule("No authentication results")
def no_auth_results(x: RiskInput):
    """No Authentication-Results header from your provider was found."""
    if not x.auth.get("trusted"):
        return "No sender-authentication results from your provider were found on this message."


# --- Header mismatches -------------------------------------------------------

@rule("Reply-To goes elsewhere")
def reply_to_mismatch(x: RiskInput):
    """Replies would go to a different organization than the From address."""
    for addr in x.reply_to:
        dom = addr.rpartition("@")[2]
        if dom and org_domain(dom) != x.from_org:
            return f"Replies go to {addr}, not to the sender's domain {x.from_org}."


@rule("Return-Path differs from From")
def return_path_mismatch(x: RiskInput):
    """The envelope sender is a different organization than From (common for
    newsletters, so low weight; skipped when DMARC passed)."""
    if x.auth.get("dmarc") == "pass" or not x.return_path:
        return None
    dom = x.return_path.rpartition("@")[2]
    if dom and org_domain(dom) != x.from_org:
        return f"The envelope sender ({dom}) is a different domain than From ({x.from_org})."


# --- Impersonation -----------------------------------------------------------

@rule("Display name imitates a brand")
def brand_impersonation(x: RiskInput):
    """The display name mentions a known brand but the address isn't one of
    that brand's domains (brands.yaml)."""
    name = x.from_name.casefold()
    if not name:
        return None
    for brand in x.brands:
        if x.from_org in _brand_domains(brand):
            continue
        for alias in [brand["name"], *brand.get("aliases", [])]:
            if re.search(rf"(?<![\w]){re.escape(alias.casefold())}(?![\w])", name):
                return f"The name says \"{brand['name']}\" but the address is at {shown(x.from_domain)}, which isn't a {brand['name']} domain."


@rule("Domain imitates a brand")
def brand_lookalike_domain(x: RiskInput):
    """The sender's domain looks like a brand's real domain (paypa1.com,
    paypal-secure.com, xn-- homoglyph domains)."""
    for brand in x.brands:
        real = _brand_domains(brand)
        if x.from_org in real:
            continue
        for d in real:
            if looks_like(x.from_domain, d) or contains_token(x.from_domain, org_label(d)):
                return f"{shown(x.from_domain)} looks like {brand['name']}'s domain {d}, but isn't."


@rule("Domain imitates a contact", history=True)
def contact_lookalike_domain(x: RiskInput):
    """The sender's domain is one or two characters away from (or a homoglyph
    of) a domain you correspond with."""
    if x.from_org in x.contact_domains:
        return None
    for d in x.contact_domains:
        if looks_like(x.from_domain, d, same_name_counts=False):
            return f"{shown(x.from_domain)} looks like {d}, a domain you write to, but isn't the same."


@rule("Name matches a contact, address doesn't", history=True)
def contact_impersonation(x: RiskInput):
    """The display name is the name of someone you've written to, but this
    address isn't one of theirs."""
    name = x.from_name.casefold().strip()
    if len(name) < 3 or " " not in name and len(name) < 5:
        return None
    addrs = x.contact_names.get(name)
    if addrs and x.from_addr not in addrs:
        return f"\"{x.from_name}\" is a contact of yours, but they've never written from {x.from_addr}."


@rule("Display name contains a different address")
def display_name_address(x: RiskInput):
    """The display name itself contains an email address that differs from
    the real sender (e.g. "support@bank.com" <x@evil.net>)."""
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", x.from_name)
    if m and m.group(0).lower() != x.from_addr:
        return f"The name shows {m.group(0)}, but the real sender is {x.from_addr}."


@rule("International lookalike domain")
def idn_domain(x: RiskInput):
    """The sender domain uses non-Latin characters that can imitate Latin ones."""
    dom = to_unicode(x.from_domain)
    if any(ord(c) > 127 for c in dom) and skeleton(dom) != dom:
        return f"The sender domain {shown(dom)} uses look-alike international characters."


@rule("First-time sender", history=True)
def first_time_sender(x: RiskInput):
    """You've never received mail from or sent mail to this address."""
    if not x.known_sender and not x.you_wrote_to_sender:
        return f"First message you've received from {x.from_addr}."


@rule("You've written to this sender")
def trusted_correspondent(x: RiskInput):
    """Negative weight: you've sent mail to this address and its domain
    authenticated (DKIM or DMARC pass)."""
    authed = x.auth.get("dmarc") == "pass" or any(d["result"] == "pass" for d in x.auth.get("dkim", []))
    if x.you_wrote_to_sender and authed:
        return "You've written to this sender before and the message authenticated."


# --- Links and attachments ---------------------------------------------------

def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


_DOMAINISH = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})(?:[/:?#]|$)", re.IGNORECASE)


@rule("Link text doesn't match destination")
def link_text_mismatch(x: RiskInput):
    """A link whose visible text is a web address points somewhere else."""
    for href, text in x.links:
        if not href.lower().startswith(("http://", "https://")):
            continue
        m = _DOMAINISH.match(text.strip())
        if not m:
            continue
        shown, real = m.group(1).lower(), _host(href)
        if real and org_domain(shown) != org_domain(real):
            return f"A link shows {shown} but actually goes to {real}."


@rule("Link to a raw IP address")
def link_ip(x: RiskInput):
    """A link points at a bare IP address instead of a domain."""
    for href, _ in x.links:
        host = _host(href).strip("[]")
        try:
            ipaddress.ip_address(host)
            return f"A link goes to the bare IP address {host}."
        except ValueError:
            continue


DANGEROUS_EXT = {
    "exe", "scr", "pif", "com", "bat", "cmd", "vbs", "vbe", "js", "jse", "wsf", "wsh",
    "hta", "msi", "msp", "jar", "lnk", "iso", "img", "vhd", "vhdx", "ps1", "reg", "cpl",
    "html", "htm", "shtml", "xhtml", "svg", "xll", "one", "appx", "dll", "chm",
}
MACRO_EXT = {"docm", "xlsm", "pptm", "dotm", "xlam"}


@rule("Risky attachment type")
def dangerous_attachment(x: RiskInput):
    """An attachment can run code or open a fake login page when opened
    (.exe, .js, .html, .iso, macro documents, double extensions...)."""
    for name in x.attachment_names:
        low = name.lower()
        parts = low.rsplit(".", 2)
        ext = parts[-1] if len(parts) > 1 else ""
        if ext in DANGEROUS_EXT or ext in MACRO_EXT:
            return f"The attachment {name} is a file type often used to deliver malware or fake login pages."
        if len(parts) == 3 and parts[-2] in {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "png", "txt"} and ext not in {"zip", "gz"}:
            return f"The attachment {name} has a misleading double extension."
