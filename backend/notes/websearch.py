"""Web search and page reading for providers that have no search of their own.

Claude searches the web natively. For every other provider (OpenRouter, OpenAI, Ollama, ...) the
assistant gets these as ordinary function tools that Kern runs itself: no extra API key needed.
Search goes through DuckDuckGo's HTML page; pages are fetched through the same SSRF-safe fetcher
the web archive uses.
"""
import html as htmllib
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests

SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
MAX_RESULTS = 8
MAX_PAGE_CHARS = 12_000


class SearchError(Exception):
    pass


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _real_url(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<encoded url>."""
    href = htmllib.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    if "uddg" in q:
        return unquote(q["uddg"][0])
    return href


def parse_results(page: str) -> list[dict]:
    out = []
    links = list(re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S))
    for i, m in enumerate(links):
        url = _real_url(m.group(1))
        if not url.startswith(("http://", "https://")):
            continue
        end = links[i + 1].start() if i + 1 < len(links) else len(page)
        snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>', page[m.end():end], re.S)
        out.append({"title": _clean(m.group(2)), "url": url, "snippet": _clean(snip.group(1)) if snip else ""})
    return out


def search(query: str, limit: int = 6) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise SearchError("Give a search query.")
    try:
        r = requests.post(SEARCH_URL, data={"q": query[:400]}, timeout=15,
                          headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        r.raise_for_status()
    except requests.RequestException as e:
        raise SearchError(f"The search engine could not be reached ({e.__class__.__name__}).")
    results = parse_results(r.text)
    if not results:
        if "anomaly" in r.text or "captcha" in r.text.lower():
            raise SearchError("The search engine is asking for a captcha right now. Try again later.")
        return []
    return results[: max(1, min(MAX_RESULTS, limit))]


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "iframe", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(page: str) -> str:
    p = _Text()
    p.feed(page)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def read(url: str) -> dict:
    from .views_web import fetch_page  # imported here: views_web pulls in the models and views

    try:
        final, ctype, body = fetch_page(url)
    except ValueError as e:
        raise SearchError(str(e))
    except requests.RequestException as e:
        raise SearchError(f"Could not load that page ({e.__class__.__name__}).")
    if ctype and not any(t in ctype for t in ("html", "text", "xml", "json")):
        raise SearchError(f"That is not a readable page ({ctype.split(';')[0]}).")
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    text = html_to_text(body) if "html" in ctype or "<html" in body[:2000].lower() else body
    truncated = len(text) > MAX_PAGE_CHARS
    return {"url": final, "title": _clean(m.group(1)) if m else "", "text": text[:MAX_PAGE_CHARS], "truncated": truncated}
