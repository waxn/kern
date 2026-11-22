import html as html_lib
import re

import nh3

INLINE_TAGS = {
    "a", "b", "strong", "i", "em", "u", "s", "strike", "del", "code",
    "span", "mark", "br", "sub", "sup",
}
INLINE_ATTRS = {
    # data-doc: a text link to a page ("link to page" in the editor), opened in a peek popup.
    "a": {"href", "class", "contenteditable", "data-ref", "data-c", "data-doc"},
    "span": {"class", "contenteditable", "data-math", "data-color"},
    "mark": {"data-bg", "data-note"},
}

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_REF_RE = re.compile(r'data-ref="(doc|block|tag):([0-9a-fA-F-]{32,36})"')
_DOC_LINK_RE = re.compile(r'data-doc="([0-9a-fA-F-]{32,36})"')
_WS_RE = re.compile(r"\s+")


def sanitize(html: str) -> str:
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=INLINE_TAGS,
        attributes=INLINE_ATTRS,
        link_rel=None,
        url_schemes={"http", "https", "mailto", "tel"},
    )


def to_text(html: str) -> str:
    if not html:
        return ""
    text = _BR_RE.sub("\n", html)
    text = _TAG_RE.sub("", text)
    return html_lib.unescape(text).replace("​", "")


def one_line(html: str, limit: int = 200) -> str:
    text = _WS_RE.sub(" ", to_text(html)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def extract_refs(html: str) -> set[tuple[str, str]]:
    """Page, block and tag references in stored HTML; text links to a page count as page references."""
    refs = {(kind, ref.lower()) for kind, ref in _REF_RE.findall(html or "")}
    return refs | {("doc", ref.lower()) for ref in _DOC_LINK_RE.findall(html or "")}
