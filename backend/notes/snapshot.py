"""Web page snapshots: the page as it looks, saved for offline viewing.

The page's stylesheets (and their @imports) are fetched and inlined; images, CSS backgrounds and
web fonts are saved under ``MEDIA_ROOT/web-pages/<bookmark>/`` and the page is rewritten to use
them. Scripts, frames, embeds, event handlers and ``javascript:`` links are removed. The result
is meant to be served by ``web_snapshot`` with a sandboxing Content-Security-Policy, so nothing in
it can run or load from the internet even if something slipped past the rewriting.
"""
import base64
from kern import tenancy
import concurrent.futures
import hashlib
import html as htmllib
import os
import re
import shutil
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

MARKER = "<!-- kern:snapshot 1 -->"
FOLDER = "web-pages"

MAX_HTML = 5_000_000
MAX_CSS = 2_000_000
MAX_ASSET = 10_000_000
MAX_TOTAL = 60_000_000
MAX_ASSETS = 300
TIME_BUDGET = 40  # seconds for all stylesheets and assets
WORKERS = 8

# Content type -> file extension. Only these are saved; the URL's own extension is never trusted.
IMAGE_TYPES = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/avif": "avif", "image/bmp": "bmp", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
}
FONT_TYPES = {
    "font/woff2": "woff2", "font/woff": "woff", "font/ttf": "ttf", "font/otf": "otf", "font/sfnt": "ttf",
    "application/font-woff": "woff", "application/font-woff2": "woff2", "application/x-font-woff": "woff",
    "application/x-font-ttf": "ttf", "application/x-font-otf": "otf", "application/vnd.ms-fontobject": "eot",
}
FONT_EXT = re.compile(r"\.(woff2?|ttf|otf|eot)$", re.I)

DROP_WITH_CONTENT = {"script", "iframe", "frame", "frameset", "object", "embed", "applet", "portal", "noembed"}
DROP_TAG = {"base", "param"}  # dropped, children (if any) kept
UNWRAP = {"noscript"}  # scripts never run here, so show what a no-script browser would see
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
URL_ATTRS = {"href", "src", "action", "poster", "cite", "background", "xlink:href", "data"}
LAZY_SRC = ("data-src", "data-lazy-src", "data-original", "data-lazy", "data-url")
LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")

CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"\s][^)]*?))\s*\)""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]+)["']?\s*\)?\s*([^;]*);""", re.I)


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + TIME_BUDGET
        self.bytes = 0
        self.count = 0

    def left(self) -> float:
        return self.deadline - time.monotonic()


def fetch(url: str, accept: str, limit: int, budget: Budget | None = None):
    """GET url, re-checking every redirect hop against the SSRF guard. Returns (final url, type, bytes)."""
    from .views_web import USER_AGENT, check_url
    for _ in range(5):
        err = check_url(url)
        if err:
            raise ValueError(err)
        timeout = 20 if budget is None else max(1.0, min(15.0, budget.left()))
        r = requests.get(url, timeout=timeout, stream=True, allow_redirects=False,
                         headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            size = int(r.headers.get("content-length") or 0)
            if size > limit:
                raise ValueError("too large")
            data = r.raw.read(limit + 1, decode_content=True)
            if len(data) > limit:
                raise ValueError("too large")
            return url, (r.headers.get("content-type") or "").split(";")[0].strip().lower(), data, r.headers.get("content-type", "")
        finally:
            r.close()
    raise ValueError("Too many redirects.")


def decode_html(data: bytes, header_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", header_type or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", data[:4096], re.I)
        enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def absolute(url: str, base: str) -> str | None:
    url = (url or "").strip()
    if not url or url.startswith(("#", "data:", "about:", "mailto:", "tel:")):
        return None
    full = urljoin(base, url)
    return full if urlparse(full).scheme in ("http", "https") else None


def safe_href(url: str, base: str) -> str:
    """Absolute link for <a href> and friends; anything that is not a web/mail link is dropped."""
    url = (url or "").strip()
    if url.startswith(("#", "mailto:", "tel:")):
        return url
    full = urljoin(base, url)
    return full if urlparse(full).scheme in ("http", "https") else "#"


def best_from_srcset(srcset: str, base: str) -> str | None:
    """One good candidate from a srcset: the largest width up to 1600px, else the smallest above."""
    cands = []
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1:
            d = bits[1].lower()
            try:
                w = float(d[:-1]) * (1 if d.endswith("w") else 800) if d[-1] in "wx" else 0
            except ValueError:
                w = 0
        u = absolute(bits[0], base)
        if u:
            cands.append((w, u))
    if not cands:
        return None
    under = [c for c in cands if c[0] <= 1600]
    return (max(under) if under else min(cands))[1]


class Snapshot:
    def __init__(self, archive_id, page_url: str):
        self.dir = os.path.join(str(tenancy.media_root()), FOLDER, str(archive_id))
        self.url_prefix = f"{settings.MEDIA_URL}{FOLDER}/{archive_id}/"
        self.base = page_url
        self.budget = Budget()
        self.assets: dict[str, str] = {}  # remote url -> local url (or data: uri)
        self.wanted: set[str] = set()
        self.styles: dict[str, str] = {}  # stylesheet url -> rewritten css (filled later)

    # ------------------------------------------------------------- css
    def collect_css(self, css: str, base: str, depth: int = 0) -> list[str]:
        """Note the assets a stylesheet uses; returns its @imported stylesheet urls."""
        imports = []
        for m in CSS_IMPORT.finditer(css):
            u = absolute(m.group(1), base)
            if u and depth < 3:
                imports.append(u)
        for m in CSS_URL.finditer(css):
            u = absolute(m.group(1) or m.group(2) or m.group(3) or "", base)
            if u:
                self.wanted.add(u)
        return imports

    def rewrite_css(self, css: str, base: str, depth: int = 0) -> str:
        def imp(m):
            u = absolute(m.group(1), base)
            media = m.group(2).strip()
            if u and u in self.styles and depth < 3:
                inner = self.rewrite_css(self.styles[u], u, depth + 1)
                return f"@media {media} {{{inner}}}" if media and media.lower() != "all" else inner
            return ""

        css = CSS_IMPORT.sub(imp, css)

        def url(m):
            raw = m.group(1) or m.group(2) or m.group(3) or ""
            if raw.strip().startswith("data:"):
                return m.group(0)
            u = absolute(raw, base)
            local = self.assets.get(u) if u else None
            return f'url("{local}")' if local else 'url("")'

        # Keep inlined CSS from closing its <style> element early.
        return CSS_URL.sub(url, css).replace("</style", "<\\/style")

    # ------------------------------------------------------------- fetching
    def fetch_styles(self, urls: list[str]):
        pending = [(u, 0) for u in dict.fromkeys(urls)]
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            while pending and self.budget.left() > 0:
                batch, pending = pending, []
                futures = {pool.submit(self._get_css, u): (u, d) for u, d in batch if u not in self.styles}
                for f in concurrent.futures.as_completed(futures):
                    u, d = futures[f]
                    css = f.result()
                    if css is None:
                        continue
                    self.styles[u] = css
                    for imp in self.collect_css(css, u, d):
                        if imp not in self.styles:
                            pending.append((imp, d + 1))

    def _get_css(self, url):
        try:
            _final, ctype, data, _h = fetch(url, "text/css,*/*;q=0.1", MAX_CSS, self.budget)
        except Exception:
            return None
        if ctype not in ("text/css", "text/plain", ""):
            return None
        return data.decode("utf-8", errors="replace")

    def fetch_assets(self):
        urls = list(self.wanted)[:MAX_ASSETS]
        os.makedirs(self.dir, exist_ok=True)
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            futures = {pool.submit(self._get_asset, u): u for u in urls}
            for f in concurrent.futures.as_completed(futures):
                local = f.result()
                if local:
                    self.assets[futures[f]] = local

    def _get_asset(self, url):
        if self.budget.left() <= 0 or self.budget.bytes > MAX_TOTAL:
            return None
        try:
            final, ctype, data, _h = fetch(url, "image/*,font/*,*/*;q=0.1", MAX_ASSET, self.budget)
        except Exception:
            return None
        self.budget.bytes += len(data)
        if self.budget.bytes > MAX_TOTAL:
            return None
        if ctype == "image/svg+xml":
            # Inline: an SVG file served from Kern's own address could run scripts if opened directly.
            return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")
        ext = IMAGE_TYPES.get(ctype) or FONT_TYPES.get(ctype)
        if not ext and ctype in ("application/octet-stream", "binary/octet-stream", ""):
            m = FONT_EXT.search(urlparse(final).path)
            ext = m.group(1).lower() if m else None
        if not ext:
            return None
        name = hashlib.sha1(url.encode()).hexdigest()[:20] + "." + ext
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)
        return self.url_prefix + name

    # ------------------------------------------------------------- run
    def build(self, page: str) -> str:
        shutil.rmtree(self.dir, ignore_errors=True)
        collector = _Pass(self, collect=True)
        collector.feed(page)
        collector.close()
        self.fetch_styles(collector.stylesheets)
        self.fetch_assets()
        writer = _Pass(self, collect=False)
        writer.feed(page)
        writer.close()
        body = "".join(writer.out)
        head = '<meta charset="utf-8"><base target="_blank">'
        if re.search(r"<head[^>]*>", body, re.I):
            body = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + head, body, count=1, flags=re.I)
        else:
            body = head + body
        return MARKER + "\n" + body


class _Pass(HTMLParser):
    """Walks the page twice: first to find what to download, then to write the snapshot."""

    def __init__(self, snap: Snapshot, collect: bool):
        super().__init__(convert_charrefs=True)
        self.s = snap
        self.collect = collect
        self.out: list[str] = []
        self.stylesheets: list[str] = []
        self.skip = 0  # inside a dropped element
        self.skip_tag = ""
        self.in_style = False
        self.style_buf: list[str] = []

    # helpers
    def asset(self, url):
        u = absolute(url, self.s.base)
        if not u:
            return url if (url or "").strip().startswith("data:") else None
        if self.collect:
            self.s.wanted.add(u)
            return None
        return self.s.assets.get(u)

    def emit_tag(self, tag, attrs, close=False):
        parts = [tag]
        for k, v in attrs:
            if v is None:
                parts.append(k)
            else:
                parts.append(f'{k}="{htmllib.escape(v, quote=True)}"')
        self.out.append("<" + " ".join(parts) + (" />" if close else ">"))

    def clean_attrs(self, tag, attrs):
        a = {}
        order = []
        for k, v in attrs:
            k = k.lower()
            if k.startswith("on") or k in ("srcdoc", "formaction", "ping", "integrity", "nonce", "crossorigin", "http-equiv"):
                continue
            if k not in a:
                order.append(k)
            a[k] = v
        # Lazy-loading: promote the real image source.
        if tag in ("img", "source"):
            for lk in LAZY_SRC:
                if a.get(lk):
                    if "src" not in a:
                        order.append("src")
                    a["src"] = a[lk]
                    break
            for lk in LAZY_SRCSET:
                if a.get(lk):
                    if "srcset" not in a:
                        order.append("srcset")
                    a["srcset"] = a[lk]
                    break
        if a.get("srcset"):
            best = best_from_srcset(a["srcset"], self.s.base)
            if best:
                if self.collect:
                    self.s.wanted.add(best)
                else:
                    local = self.s.assets.get(best)
                    if local:
                        if tag == "img":
                            if "src" not in a:
                                order.append("src")
                            a["src"] = local
                            a.pop("srcset", None)
                            a.pop("sizes", None)
                        else:
                            a["srcset"] = local
                            a.pop("sizes", None)
        for k in list(a):
            v = a[k]
            if v is None:
                continue
            if k == "style":
                if self.collect:
                    self.s.collect_css(v, self.s.base)
                else:
                    a[k] = self.s.rewrite_css(v, self.s.base)
            elif k in ("src", "poster", "background") and tag in ("img", "source", "video", "input", "image", "td", "table", "body"):
                if tag == "source" and k == "src":  # <video>/<audio> media: not downloaded
                    a.pop(k)
                    continue
                if v.startswith(self.s.url_prefix):  # already the saved copy (from srcset)
                    continue
                local = self.asset(v)
                if not self.collect:
                    if local:
                        a[k] = local
                    else:
                        a.pop(k)
            elif k == "srcset":
                if not self.collect and not a[k].startswith(self.s.url_prefix):
                    a.pop(k)
            elif k in URL_ATTRS or k.endswith(":href"):
                if tag in ("video", "audio") and k == "src":
                    a.pop(k)
                    continue
                if not self.collect:
                    a[k] = safe_href(v, self.s.base)
        return [(k, a[k]) for k in order if k in a]

    # parser events
    def handle_decl(self, decl):
        if not self.collect and not self.skip:
            self.out.append(f"<!{decl}>")

    def handle_starttag(self, tag, attrs, close=False):
        if self.skip:
            if tag == self.skip_tag and not close:
                self.skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            if not close and tag not in VOID:
                self.skip, self.skip_tag = 1, tag
            return
        if tag in DROP_TAG or tag in UNWRAP:
            if tag == "base":
                href = dict(attrs).get("href")
                if href:
                    self.s.base = urljoin(self.s.base, href)
            return
        if tag == "meta":
            names = {k.lower() for k, _ in attrs}
            if "http-equiv" in names or "charset" in names:
                return
        if tag == "link":
            d = {k.lower(): (v or "") for k, v in attrs}
            rel = d.get("rel", "").lower().split()
            if "stylesheet" in rel and d.get("href"):
                u = absolute(d["href"], self.s.base)
                if not u:
                    return
                if self.collect:
                    self.stylesheets.append(u)
                elif u in self.s.styles:
                    media = d.get("media")
                    css = self.s.rewrite_css(self.s.styles[u], u)
                    self.out.append(f'<style{" media=" + chr(34) + htmllib.escape(media) + chr(34) if media else ""}>{css}</style>')
                return
            if not ({"icon", "shortcut", "apple-touch-icon"} & set(rel)):
                return  # preload, prefetch, manifest, alternate, ...: nothing to keep offline
            local = self.asset(d.get("href"))
            if self.collect or not local:
                return
            attrs = [(k, local if k.lower() == "href" else v) for k, v in attrs]
            self.emit_tag(tag, attrs, close)
            return
        if tag == "style":
            self.in_style = True
            self.style_buf = []
        attrs = self.clean_attrs(tag, attrs)
        if not self.collect:
            self.emit_tag(tag, attrs, close)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, close=True)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag:
                self.skip -= 1
            return
        if tag in DROP_WITH_CONTENT or tag in DROP_TAG or tag in UNWRAP or tag in VOID:
            return
        if tag == "style" and self.in_style:
            self.in_style = False
            css = "".join(self.style_buf)
            if self.collect:
                for imp in self.s.collect_css(css, self.s.base):
                    self.stylesheets.append(imp)
            else:
                self.out.append(self.s.rewrite_css(css, self.s.base))
        if not self.collect:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_style:
            self.style_buf.append(data)
            return
        if not self.collect:
            self.out.append(htmllib.escape(data, quote=False))

    def handle_comment(self, data):
        pass

    def handle_pi(self, data):
        pass


def capture(archive_id, url: str) -> tuple[str, str, str]:
    """Fetch url and snapshot it. Returns (final url, content type, snapshot html)."""
    final, ctype, data, header = fetch(url, "text/html,application/xhtml+xml,*/*;q=0.5", MAX_HTML)
    page = decode_html(data, header)
    if "html" not in ctype and not page.lstrip()[:200].lower().startswith(("<!doctype html", "<html")):
        return final, ctype, ""
    return final, ctype, Snapshot(archive_id, final).build(page)


def remove(archive_id) -> None:
    shutil.rmtree(os.path.join(str(tenancy.media_root()), FOLDER, str(archive_id)), ignore_errors=True)


def is_snapshot(html: str) -> bool:
    return bool(html) and html.startswith(MARKER)


MIME_BY_EXT = {
    **{ext: t for t, ext in IMAGE_TYPES.items() if t not in ("image/jpg", "image/vnd.microsoft.icon")},
    **{"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "otf": "font/otf", "eot": "application/vnd.ms-fontobject"},
}


def self_contained(archive_id, html: str) -> str:
    """The snapshot with its saved assets inlined as data: URIs.

    The page is shown sandboxed (an opaque origin), and browsers increasingly refuse requests
    from such pages to the local network, Kern itself included. Inlining at serve time means
    the browser makes no requests at all, while the assets stay as files on disk.
    """
    prefix = f"{settings.MEDIA_URL}{FOLDER}/{archive_id}/"
    folder = os.path.join(str(tenancy.media_root()), FOLDER, str(archive_id))
    cache: dict[str, str] = {}

    def inline(m):
        name = m.group(1)
        if name not in cache:
            ext = name.rsplit(".", 1)[-1].lower()
            path = os.path.join(folder, name)
            mime = MIME_BY_EXT.get(ext)
            try:
                with open(path, "rb") as f:
                    cache[name] = f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii") if mime else ""
            except OSError:
                cache[name] = ""
        return cache[name]

    return re.sub(re.escape(prefix) + r"([0-9a-f]{20}\.[a-z0-9]{2,5})", inline, html)
