"""Watching bookmarked pages for changes, and keeping their history.

A watched bookmark is fetched every ``monitor_interval`` minutes by a background scheduler that
runs in each server process (several processes may run it: every check is claimed with a
conditional update first, so a page is only fetched once per interval). What counts as a change
depends on the bookmark's mode:

* ``posts``: new entries in the site's RSS/Atom feed, or, without one, new article links;
* ``price``: the product's price, read from its structured data (JSON-LD, meta tags);
* ``content``: any change to the page's readable text;
* ``auto``: one of the above, picked on the first check from what the page offers.

Each change can save a full snapshot of the page to the bookmark's history (``WebSnapshot``),
which can be viewed and compared like the Wayback Machine. A version's images and fonts are
hard links to the capture they came from, so versions only cost disk space for what changed.
"""
import difflib
import hashlib
import html as htmllib
import json
import logging
import os
import random
import re
import shutil
import threading
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from kern import tenancy

from .models_web import WebArchive, WebSnapshot

log = logging.getLogger(__name__)

MODES = ("auto", "posts", "price", "content")
MIN_INTERVAL = 30  # minutes
MAX_INTERVAL = 60 * 24 * 30
MAX_TEXT = 300_000  # readable text kept per version
MAX_STATE_TEXT = 150_000  # text kept as the "content" baseline
MAX_SEEN = 500  # post keys remembered
MAX_FEED = 3_000_000
KEEP_VERSIONS = 100  # per bookmark; the oldest (the original) is always kept
PRICE_HISTORY = 200
TICK = 60  # seconds between scheduler passes
PER_TICK = 8  # checks per user per pass


# ------------------------------------------------------------------ text


def page_text(page: str) -> str:
    """The page's readable text, one line per block, without blank lines."""
    from .websearch import html_to_text

    lines = (ln.strip() for ln in html_to_text(page or "").splitlines())
    return "\n".join(ln for ln in lines if ln)[:MAX_TEXT]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _clean(s) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ posts


FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/xml", "text/xml")
ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def looks_like_feed(ctype: str, body) -> bool:
    head = (body[:600] if isinstance(body, str) else body[:600].decode("utf-8", "ignore")).lower()
    if "<html" in head:
        return False
    return "xml" in (ctype or "").lower() and ("<rss" in head or "<feed" in head or "<rdf" in head) or (
        head.lstrip().startswith("<?xml") and ("<rss" in head or "<feed" in head or "<rdf" in head)
    )


def find_feed(page: str, base: str) -> str:
    """The page's RSS/Atom feed, from its <link rel="alternate"> tags. Comment feeds are skipped."""
    for m in re.finditer(r"<link\b[^>]*>", page[:400_000], re.I):
        attrs = {k.lower(): (a or b or c) for k, a, b, c in ATTR.findall(m.group(0))}
        rel = attrs.get("rel", "").lower().split()
        kind = attrs.get("type", "").lower()
        href = attrs.get("href", "")
        title = attrs.get("title", "").lower()
        if "alternate" in rel and kind in FEED_TYPES[:3] and href and "comment" not in title + href.lower():
            full = urljoin(base, htmllib.unescape(href))
            if urlparse(full).scheme in ("http", "https"):
                return full
    return ""


def parse_feed(data) -> list[dict]:
    """Entries of an RSS or Atom feed, newest first as the feed lists them."""
    if isinstance(data, str):
        data = re.sub(r"^\s*<\?xml[^>]*\?>", "", data).encode("utf-8")
    # No document type: it is where entity definitions (and entity-expansion attacks) live.
    data = re.sub(rb"<!DOCTYPE[^>\[]*(\[.*?\])?\s*>", b"", data[:MAX_FEED], flags=re.S | re.I)
    root = ET.fromstring(data)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    def txt(el, name):
        c = el.find(name)
        return _clean(c.text) if c is not None and c.text else ""

    out = []
    for item in root.iter("item"):  # RSS (and RDF)
        link = txt(item, "link") or (item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "")
        title = txt(item, "title")
        key = txt(item, "guid") or link or title
        if key:
            out.append({"key": key[:500], "title": title[:300], "url": link[:2048],
                        "date": txt(item, "pubDate") or txt(item, "date")})
    for entry in root.iter("entry"):  # Atom
        link = ""
        for ln in entry.findall("link"):
            if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                link = ln.get("href")
                break
        title = txt(entry, "title")
        key = txt(entry, "id") or link or title
        if key:
            out.append({"key": key[:500], "title": title[:300], "url": link[:2048],
                        "date": txt(entry, "published") or txt(entry, "updated")})
    return out[:150]


class _Links(HTMLParser):
    """Links on a page, noting which sit in an article, a heading or the main content."""

    CONTEXT = {"article", "h1", "h2", "h3", "h4", "main"}
    SKIP = {"nav", "footer", "header", "aside", "script", "style", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ctx = 0
        self.skip = 0
        self.cur: dict | None = None
        self.links: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.CONTEXT:
            self.ctx += 1
        if tag == "a":
            href = dict(attrs).get("href")
            self.cur = {"href": href, "text": [], "ctx": self.ctx > 0} if href and not self.skip else None

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        if tag in self.CONTEXT:
            self.ctx = max(0, self.ctx - 1)
        if tag == "a" and self.cur:
            self.cur["text"] = re.sub(r"\s+", " ", "".join(self.cur["text"])).strip()
            self.links.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None:
            self.cur["text"].append(data)


def page_posts(page: str, base: str) -> list[dict]:
    """Likely post links on a page without a feed: same-site links with a headline-like text."""
    p = _Links()
    try:
        p.feed(page)
        p.close()
    except Exception:
        pass
    host = (urlparse(base).hostname or "").lower().removeprefix("www.")
    here = base.split("#")[0].rstrip("/")
    picked: dict[str, dict] = {}
    for prefer_ctx in (True, False):
        for ln in p.links:
            if prefer_ctx and not ln["ctx"]:
                continue
            url = urljoin(base, ln["href"]).split("#")[0]
            u = urlparse(url)
            if u.scheme not in ("http", "https") or (u.hostname or "").lower().removeprefix("www.") != host:
                continue
            if url.rstrip("/") == here or u.path in ("", "/") or len(ln["text"]) < 12:
                continue
            picked.setdefault(url, {"key": url[:500], "title": ln["text"][:300], "url": url[:2048], "date": ""})
        if len(picked) >= 3:
            break
    return list(picked.values())[:200]


# ------------------------------------------------------------------ prices


SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
SHOW = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹"}
TEXT_PRICE = re.compile(
    r"(?P<sym>[$€£¥₹])\s?(?P<a>\d[\d.,  ]{0,14}\d|\d)"
    r"|(?P<b>\d[\d.,  ]{0,14}\d|\d)\s?(?P<cur>kr|SEK|NOK|DKK|EUR|USD|GBP|€|:-)(?![a-zA-Z])"
)


def parse_amount(raw) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[^\d.,]", "", str(raw or ""))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) and s.count(",") == 1 else s.replace(",", "")
    elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def price_display(amount: float, currency: str) -> str:
    num = f"{int(amount):,}" if amount == int(amount) else f"{amount:,.2f}"
    sym = SHOW.get(currency.upper())
    return f"{sym}{num}" if sym else f"{num} {currency}".strip()


def _ld_prices(node, out):
    if isinstance(node, list):
        for n in node:
            _ld_prices(n, out)
    elif isinstance(node, dict):
        for key in ("price", "lowPrice"):
            if key in node and node[key] not in (None, ""):
                amount = parse_amount(node[key])
                if amount is not None:
                    out.append((amount, str(node.get("priceCurrency") or "")))
                    break
        for v in node.values():
            if isinstance(v, (dict, list)):
                _ld_prices(v, out)


def find_price(page: str, text: str | None = None) -> dict | None:
    """The page's price: from JSON-LD, then product meta tags, then itemprop, then visible text."""
    from .views_web import meta_content

    found: list[tuple[float, str]] = []
    for m in re.finditer(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.I | re.S):
        try:
            _ld_prices(json.loads(m.group(1).strip().removeprefix("<!--").removesuffix("-->")), found)
        except (ValueError, RecursionError):
            continue
    source = "structured"
    if not found:
        amount = parse_amount(meta_content(page, "product:price:amount", "og:price:amount"))
        if amount is not None:
            found.append((amount, meta_content(page, "product:price:currency", "og:price:currency")))
    if not found:
        m = re.search(r"""itemprop=["']price["'][^>]*content=["']([^"']+)""", page, re.I) or re.search(
            r"""content=["']([^"']+)["'][^>]*itemprop=["']price["']""", page, re.I)
        cur = re.search(r"""itemprop=["']priceCurrency["'][^>]*content=["']([^"']+)""", page, re.I)
        amount = parse_amount(m.group(1)) if m else None
        if amount is not None:
            found.append((amount, cur.group(1) if cur else ""))
    if not found:
        source = "text"
        m = TEXT_PRICE.search(text if text is not None else page_text(page))
        if m:
            amount = parse_amount(m.group("a") or m.group("b"))
            cur = SYMBOLS.get(m.group("sym") or "", "") or {"kr": "SEK", ":-": "SEK", "€": "EUR"}.get(m.group("cur") or "", m.group("cur") or "")
            if amount is not None:
                found.append((amount, cur))
    if not found:
        return None
    amount, currency = found[0]
    currency = currency.strip().upper()[:8]
    return {"amount": amount, "currency": currency, "display": price_display(amount, currency), "source": source}


# ------------------------------------------------------------------ history


def version_key(vid) -> str:
    return f"v{vid}"


def _link_tree(src: str, dst: str) -> int:
    """Hard-link (or, across file systems, copy) a capture's files into a version's folder."""
    size = 0
    if not os.path.isdir(src):
        return 0
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if not os.path.isfile(s):
            continue
        try:
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)
        size += os.path.getsize(d)
    return size


def record_version(a: WebArchive, trigger: str, change: dict | None = None, final_url: str = "",
                   skip_unchanged: bool = False) -> WebSnapshot | None:
    """Save the bookmark's current capture (``html_content``) as a version in its history."""
    from . import snapshot

    html = a.html_content or ""
    text = page_text(html)
    h = text_hash(text)
    if skip_unchanged:
        last = a.snapshots.only("text_hash").first()
        if last and last.text_hash == h:
            return None
    price = (a.monitor_state or {}).get("price") or {}
    v = WebSnapshot.objects.create(
        archive=a, trigger=trigger, url=(final_url or a.url)[:2048], title=a.title[:500], text=text,
        text_hash=h, change=change or {}, price=str(price.get("display", ""))[:64],
    )
    size = 0
    if snapshot.is_snapshot(html):
        root = os.path.join(str(tenancy.media_root()), snapshot.FOLDER)
        size = _link_tree(os.path.join(root, str(a.id)), os.path.join(root, version_key(v.id)))
        html = html.replace(f"{settings.MEDIA_URL}{snapshot.FOLDER}/{a.id}/",
                            f"{settings.MEDIA_URL}{snapshot.FOLDER}/{version_key(v.id)}/")
    v.html = html
    v.size = size + len(html.encode("utf-8", "replace"))
    v.save(update_fields=["html", "size"])
    prune(a)
    return v


def remove_version(v: WebSnapshot) -> None:
    from . import snapshot

    snapshot.remove(version_key(v.id))
    v.delete()


def remove_history(a: WebArchive) -> None:
    from . import snapshot

    for vid in a.snapshots.values_list("id", flat=True):
        snapshot.remove(version_key(vid))


def prune(a: WebArchive, keep: int = KEEP_VERSIONS) -> None:
    ids = list(a.snapshots.values_list("id", flat=True))  # newest first
    if len(ids) <= keep:
        return
    oldest = ids[-1]
    for v in WebSnapshot.objects.filter(id__in=[i for i in ids[keep - 1:] if i != oldest]):
        remove_version(v)


def diff(old: str, new: str, context: int = 3, limit: int = 4000) -> dict:
    """Line diff of two versions' text: hunks of equal (collapsed), removed and added lines."""
    a, b = old.splitlines(), new.splitlines()
    ops, added, removed, shown = [], 0, 0, 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if shown > limit:
            ops.append({"op": "skip", "count": (i2 - i1) + (j2 - j1)})
            continue
        if tag == "equal":
            lines = a[i1:i2]
            if len(lines) > context * 2 + 1:
                if ops:
                    ops.append({"op": "eq", "lines": lines[:context]})
                ops.append({"op": "skip", "count": len(lines) - (context * 2 if ops else context)})
                ops.append({"op": "eq", "lines": lines[-context:]})
            else:
                ops.append({"op": "eq", "lines": lines})
            shown += min(len(lines), context * 2)
            continue
        if tag in ("delete", "replace"):
            ops.append({"op": "del", "lines": a[i1:i2]})
            removed += i2 - i1
            shown += i2 - i1
        if tag in ("insert", "replace"):
            ops.append({"op": "add", "lines": b[j1:j2]})
            added += j2 - j1
            shown += j2 - j1
    if not (added or removed):
        ops = []  # identical
    return {"added": added, "removed": removed, "ops": ops}


def _content_change(old: str, new: str) -> dict | None:
    a, b = old.splitlines(), new.splitlines()
    added, removed, snippets = 0, 0, []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            removed += i2 - i1
        if tag in ("insert", "replace"):
            added += j2 - j1
            snippets += [ln[:200] for ln in b[j1:j2] if len(ln) > 3][: 6 - len(snippets)]
    if not (added or removed):
        return None
    return {"type": "content", "added": added, "removed": removed, "snippets": snippets[:6]}


# ------------------------------------------------------------------ checking


def resolve_mode(page: str, base: str, is_feed: bool) -> str:
    if is_feed:
        return "posts"
    p = find_price(page)
    if p and p["source"] == "structured":
        return "price"
    if find_feed(page, base):
        return "posts"
    return "content"


def interval_of(a: WebArchive) -> timedelta:
    return timedelta(minutes=max(MIN_INTERVAL, min(MAX_INTERVAL, a.monitor_interval or 1440)))


def next_time(a: WebArchive, now=None):
    # A little jitter, so bookmarks added together do not all fetch at the same moment.
    return (now or timezone.now()) + interval_of(a) + timedelta(seconds=random.randint(0, 120))


def _posts(a, state, final, body, is_feed) -> tuple[list[dict], str]:
    from . import snapshot

    if is_feed:
        try:
            return parse_feed(body), ""
        except ET.ParseError:
            return [], "The feed could not be read."
    feed = state.get("feed_url") or find_feed(body, final)
    if feed:
        try:
            _u, _t, data, _h = snapshot.fetch(feed, "application/rss+xml,application/atom+xml,application/xml,*/*;q=0.2", MAX_FEED)
            items = parse_feed(data)
            if items:
                state["feed_url"] = feed
                return items, ""
        except Exception:
            pass
        state.pop("feed_url", None)
    items = page_posts(body, final)
    return items, "" if items else "No posts or feed found on this page. Try watching for any change instead."


def check(a: WebArchive, trigger: str = "change") -> dict | None:
    """Fetch the page once and compare it with the last check. Returns the change found, if any."""
    from .views_web import fetch_page, save_html

    now = timezone.now()
    state = dict(a.monitor_state or {})
    fields = ["monitor_state", "monitor_error", "last_checked_at", "next_check_at"]
    a.last_checked_at = now
    a.next_check_at = next_time(a, now) if a.monitor_enabled else None
    try:
        final, ctype, body = fetch_page(a.url)
    except Exception as e:
        a.monitor_error = f"Couldn't load the page: {e}"[:1000]
        a.save(update_fields=fields)
        return None

    is_feed = looks_like_feed(ctype, body)
    first = not state.get("checked")
    mode = a.monitor_mode if a.monitor_mode in MODES[1:] else (state.get("mode") or resolve_mode(body, final, is_feed))
    text = "" if is_feed else page_text(body)
    change, error = None, ""

    if mode == "posts":
        items, error = _posts(a, state, final, body, is_feed)
        seen = state.get("seen") or []
        known = set(seen)
        if items and not first:
            new = [i for i in items if i["key"] not in known]
            if new:
                change = {"type": "posts", "count": len(new),
                          "added": [{k: i[k] for k in ("title", "url", "date")} for i in new[:20]]}
        if items:
            keys = [i["key"] for i in items]
            fresh = set(keys)
            state["seen"] = (keys + [k for k in seen if k not in fresh])[:MAX_SEEN]
            state["latest"] = [{k: i[k] for k in ("title", "url", "date")} for i in items[:8]]
    elif mode == "price":
        p = find_price(body, text)
        if not p:
            error = "Couldn't find a price on this page."
        else:
            old = state.get("price")
            history = state.get("price_history") or []
            if old and not first and abs(old["amount"] - p["amount"]) > 1e-9:
                change = {"type": "price", "old": old, "new": p}
            if not history or abs(history[-1]["amount"] - p["amount"]) > 1e-9:
                history.append({"at": now.isoformat(), "amount": p["amount"], "display": p["display"]})
            state["price"] = p
            state["price_history"] = history[-PRICE_HISTORY:]
    else:
        h = text_hash(text)
        if not first and h != state.get("hash"):
            change = _content_change(state.get("text", ""), text)
        state["hash"] = h
        state["text"] = text[:MAX_STATE_TEXT]

    state.update(checked=True, mode=mode)
    if change:
        state["last_change"] = {**change, "at": now.isoformat()}
        a.last_changed_at = now
        a.unseen_changes = (a.unseen_changes or 0) + 1
        fields += ["last_changed_at", "unseen_changes"]
    a.monitor_state = state
    a.monitor_error = error
    a.save(update_fields=fields)

    if change and a.monitor_archive and a.kind in ("web", "mixed"):
        # The bookmark shows the page as it is now; the history keeps what it was.
        try:
            if not a.snapshots.exists() and a.html_content:
                record_version(a, "saved")
            save_html(a, final, body)
            a.save(update_fields=["html_content", "updated_at"])
            record_version(a, trigger, change, final)
        except Exception:
            log.exception("saving a version of bookmark %s failed", a.id)
    elif first and a.monitor_archive and a.html_content and not a.snapshots.exists():
        record_version(a, "saved")  # a baseline to compare later versions with
    return change


# ------------------------------------------------------------------ scheduler


def due(now=None):
    now = now or timezone.now()
    return WebArchive.objects.filter(monitor_enabled=True).filter(
        Q(next_check_at__isnull=True) | Q(next_check_at__lte=now)
    ).order_by("next_check_at")


def claim(a: WebArchive, now=None) -> bool:
    """Take this check for this process: only one process's conditional update succeeds."""
    qs = WebArchive.objects.filter(id=a.id, monitor_enabled=True)
    qs = qs.filter(next_check_at__isnull=True) if a.next_check_at is None else qs.filter(next_check_at=a.next_check_at)
    nxt = next_time(a, now)
    if qs.update(next_check_at=nxt) != 1:
        return False
    a.next_check_at = nxt
    return True


def run_due(limit: int = PER_TICK) -> int:
    done = 0
    for a in list(due()[:limit]):
        if not claim(a):
            continue
        try:
            check(a)
        except Exception:
            log.exception("checking bookmark %s failed", a.id)
        done += 1
    return done


def tick() -> None:
    from django.contrib.auth import get_user_model

    for uid in get_user_model().objects.filter(is_active=True).values_list("id", flat=True):
        if not (tenancy.user_dir(uid) / "kern.sqlite3").exists():
            continue
        try:
            with tenancy.use(uid):
                run_due()
        except Exception:
            log.exception("monitor pass for user %s failed", uid)
    tenancy.close_connections()


_started = False
_start_lock = threading.Lock()


def start() -> None:
    """Run the scheduler in a daemon thread of this process (once). KERN_NO_MONITOR=1 turns it off."""
    global _started
    if os.environ.get("KERN_NO_MONITOR") or tenancy.testing():
        return
    with _start_lock:
        if _started:
            return
        _started = True

    def loop():
        time.sleep(15)
        while True:
            try:
                tick()
            except Exception:
                log.exception("monitor pass failed")
            time.sleep(TICK)

    threading.Thread(target=loop, name="kern-monitor", daemon=True).start()
