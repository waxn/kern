"""Email HTML sanitizer.

SECURITY (review carefully): this is layer 1 of 3 against hostile email.

  1. Here: an allowlist sanitizer (nh3 / ammonia, a real HTML5 parser) drops
     scripts, event handlers, forms, frames, SVG/MathML, <base>, <meta>, and
     any URL that isn't http(s)/mailto. Remote images and CSS url()s are
     removed, or rewritten to go through the signed image proxy when you
     click "load images".
  2. The frontend renders the result in an <iframe sandbox> WITHOUT
     allow-scripts (see frontend/src/lib/emailFrame.js).
  3. A strict CSP: the app's own policy (inherited by the iframe) plus a
     <meta> CSP inside the frame with script-src 'none'.

Any one layer is meant to be enough on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import nh3

from . import imgproxy

ALLOWED_TAGS = {
    "a", "abbr", "acronym", "address", "article", "aside", "b", "bdi", "bdo", "big",
    "blockquote", "br", "caption", "center", "cite", "code", "col", "colgroup", "dd",
    "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "font",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "i", "img",
    "ins", "kbd", "li", "main", "mark", "nav", "ol", "p", "pre", "q", "rp", "rt", "ruby",
    "s", "samp", "section", "small", "span", "strike", "strong", "style", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr",
    "tt", "u", "ul", "var", "wbr",
}
# Removed together with everything inside them.
DROP_WITH_CONTENT = {
    "script", "title", "noscript", "template", "iframe", "frame", "frameset", "object",
    "embed", "applet", "svg", "math", "xmp", "plaintext", "noembed", "noframes",
    "select", "textarea", "button", "audio", "video", "canvas", "head", "meta", "link",
}
GENERIC_ATTRS = {
    "style", "class", "id", "dir", "lang", "title", "align", "valign", "bgcolor",
    "width", "height", "border", "color", "face", "size", "role", "aria-label",
    "aria-hidden",
}
TAG_ATTRS = {
    "a": {"href", "name"},
    "img": {"src", "alt"},
    "table": {"cellpadding", "cellspacing", "summary", "frame", "rules"},
    "td": {"colspan", "rowspan", "nowrap", "headers", "scope", "abbr", "axis"},
    "th": {"colspan", "rowspan", "nowrap", "headers", "scope", "abbr", "axis"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "type", "reversed"},
    "ul": {"type"},
    "li": {"value", "type"},
    "time": {"datetime"},
    "font": {"color", "face", "size"},
    "details": {"open"},
    "hr": {"noshade"},
}
URL_SCHEMES = {"http", "https", "mailto", "cid"}

_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_DANGER = re.compile(
    r"(@import[^;]*;?|expression\s*\(|behaviou?r\s*:|-moz-binding|javascript:|vbscript:)",
    re.IGNORECASE,
)
_STYLE_BLOCK = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)


@dataclass
class SanitizeResult:
    html: str
    remote_images: int  # how many remote resources were blocked (or proxied)
    colors: str = "none"  # how colors were fitted to Kern's theme (mail/colors.py)


class _Ctx:
    def __init__(self, message_pk: int, load_images: bool, cid_map: dict[str, int]):
        self.message_pk = message_pk
        self.load_images = load_images
        self.cid_map = {k.lower(): v for k, v in cid_map.items()}
        self.remote = 0

    def remote_url(self, url: str) -> str | None:
        self.remote += 1
        if self.load_images:
            return imgproxy.signed_path(url)
        return None

    def cid_url(self, cid: str) -> str | None:
        att = self.cid_map.get(cid.strip("<>").lower())
        if att is None:
            return None
        return f"/api/mail/messages/{self.message_pk}/attachments/{att}?inline=1"

    def css(self, css: str) -> str:
        css = _CSS_DANGER.sub("", css)

        def repl(m):
            url = m.group(2).strip()
            low = url.lower()
            if low.startswith(("http://", "https://", "//")):
                if low.startswith("//"):
                    url = "https:" + url
                new = self.remote_url(url)
                return f"url('{new}')" if new else "none"
            if low.startswith("cid:"):
                new = self.cid_url(url[4:])
                return f"url('{new}')" if new else "none"
            if low.startswith("data:image/") and ";base64," in low and "svg" not in low[:20]:
                return m.group(0)
            return "none"

        return _CSS_URL.sub(repl, css)

    def attribute_filter(self, tag: str, attr: str, value: str):
        if attr == "style":
            return self.css(value)
        if tag == "img" and attr == "src":
            v = value.strip()
            low = v.lower()
            if low.startswith("cid:"):
                return self.cid_url(v[4:])
            if low.startswith(("http://", "https://")):
                return self.remote_url(v)
            return None
        if tag == "a" and attr == "href":
            v = value.strip()
            if v.lower().startswith(("http://", "https://", "mailto:")):
                return v
            return None
        if attr == "id":
            return re.sub(r"[^\w-]", "", value)[:64] or None
        return value


def sanitize_html(markup: str, *, message_pk: int = 0, load_images: bool = False,
                  cid_map: dict[str, int] | None = None, theme: str = "") -> SanitizeResult:
    """theme "dark" or "light" fits the email's colors to Kern's page (mail/colors.py);
    empty keeps them as sent."""
    from . import colors as colors_mod

    ctx = _Ctx(message_pk, load_images, cid_map or {})
    attributes = {"*": set(GENERIC_ATTRS)}
    for tag, attrs in TAG_ATTRS.items():
        attributes[tag] = set(attrs)
    cleaned = nh3.clean(
        markup,
        tags=ALLOWED_TAGS,
        clean_content_tags=DROP_WITH_CONTENT,
        attributes=attributes,
        attribute_filter=ctx.attribute_filter,
        strip_comments=True,
        link_rel="noopener noreferrer nofollow",
        url_schemes=URL_SCHEMES,
        # Relative URLs from the email are already dropped by attribute_filter;
        # only our own rewritten proxy/attachment URLs may be relative.
        url_relative=lambda u: u if u.startswith(("/api/mail/img?", "/api/mail/messages/")) else None,
        set_tag_attribute_values={"a": {"target": "_blank"}},
        id_prefix="m-",
    )

    def style_repl(m):
        body = ctx.css(m.group(2))
        # Never let a style block close itself early or open markup.
        body = body.replace("<", "\\3c ")
        return m.group(1) + body + m.group(3)

    cleaned = _STYLE_BLOCK.sub(style_repl, cleaned)
    # <body> is dropped above; keep the colors it set (parsed, re-serialized: never raw text).
    bg, fg = colors_mod.body_colors(markup)
    if bg or fg:
        css = (f"background-color:{bg};" if bg else "") + (f"color:{fg};" if fg else "")
        cleaned = f'<div style="{css}">{cleaned}</div>'
    how = "none"
    if theme:
        cleaned, how = colors_mod.adapt(cleaned, theme)
    return SanitizeResult(html=cleaned, remote_images=ctx.remote, colors=how)


_URL_IN_TEXT = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]])", re.IGNORECASE)


def linkify_text(text: str) -> str:
    """Escape plain text and turn bare URLs into safe links."""
    import html as _html

    out, last = [], 0
    for m in _URL_IN_TEXT.finditer(text):
        out.append(_html.escape(text[last:m.start()]))
        url = m.group(1)
        out.append(
            f'<a href="{_html.escape(url, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer nofollow">{_html.escape(url)}</a>'
        )
        last = m.end()
    out.append(_html.escape(text[last:]))
    return "".join(out)


def mailto_safe(addr: str) -> str:
    return "mailto:" + quote(addr, safe="@.+-_")
