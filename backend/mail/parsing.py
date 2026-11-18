"""Robust RFC 822 / MIME parsing for real-world (often broken) email.

Principles:
* Never raise on bad input. Every field degrades to something displayable,
  and problems are recorded in `defects`.
* Decode text with the declared charset, then UTF-8, then Windows-1252, then
  Latin-1 (which can't fail).
* Never descend into attached message/rfc822 parts: a forwarded message is an
  attachment, not part of this message's body.
"""

from __future__ import annotations

import codecs
import email
import email.header
import email.utils
import html
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import Message as EmailMessage
from email.policy import compat32
from html.parser import HTMLParser

MAX_PARTS = 500
MAX_DEPTH = 30
MAX_TEXT_CHARS = 500_000
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_REFERENCES = 60

CHARSET_ALIASES = {
    "x-mac-roman": "mac_roman",
    "macintosh": "mac_roman",
    "windows-874": "cp874",
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "x-gbk": "gb18030",
    "x-sjis": "shift_jis",
    "sjis": "shift_jis",
    "iso-8859-8-i": "iso-8859-8",
    "ks_c_5601-1987": "cp949",
    "x-user-defined": "cp1252",
    "ansi_x3.4-1968": "cp1252",
    # us-ascii is constantly mislabelled; treat as its superset.
    "us-ascii": "utf-8",
    "ascii": "utf-8",
    "utf8": "utf-8",
    "unicode-1-1-utf-7": "utf-7",
    "latin1": "cp1252",
    "iso-8859-1": "cp1252",  # browsers do this too (WHATWG)
}

KEPT_HEADERS = (
    "list-id", "list-unsubscribe", "list-unsubscribe-post", "list-post",
    "return-path", "sender", "precedence", "auto-submitted",
    "x-mailer", "user-agent", "received-spf",
)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"\s+")
_MSGID = re.compile(r"<([^<>\s]{1,900})>")
_SUBJECT_PREFIX = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|wg|sv|vs|antw|ref|tr|rif|r|odp|vb|bls)\s*(?:\[\d+\]|\(\d+\))?\s*[:：]\s*|\[[^\]]{1,40}\]\s*)",
    re.IGNORECASE,
)


# --- Text decoding -----------------------------------------------------------

def _codec(charset: str | None) -> str | None:
    if not charset:
        return None
    cs = charset.strip().strip('"').strip("'").lower()
    cs = CHARSET_ALIASES.get(cs, cs)
    try:
        return codecs.lookup(cs).name
    except LookupError:
        return None


def decode_bytes(data: bytes, charset: str | None = None) -> tuple[str, bool]:
    """Decode bytes; returns (text, clean) where clean=False means a fallback
    was used."""
    declared = _codec(charset)
    # Valid multi-byte UTF-8 labelled as a single-byte Western charset is
    # almost always really UTF-8 (a very common mislabel).
    if declared in ("cp1252", "iso8859-1", "iso8859-15") and any(b > 0x7F for b in data):
        try:
            return data.decode("utf-8"), False
        except UnicodeDecodeError:
            pass
    tried = []
    for cs in (declared, "utf-8", "cp1252"):
        if cs and cs not in tried:
            tried.append(cs)
            try:
                return data.decode(cs), cs == declared
            except (UnicodeDecodeError, LookupError):
                continue
    return data.decode(declared or "latin-1", errors="replace"), False


def _unsurrogate(value: str) -> str:
    """compat32 keeps raw 8-bit header bytes as surrogate escapes; recover them."""
    if not any("\udc80" <= ch <= "\udcff" for ch in value):
        return value
    raw = value.encode("ascii", "surrogateescape")
    return decode_bytes(raw)[0]


def clean_text(value: str) -> str:
    return _WS.sub(" ", _CTRL.sub("", value)).strip()


def decode_header_value(value) -> str:
    """Decode an RFC 2047 header value, tolerating every kind of breakage."""
    if value is None:
        return ""
    if isinstance(value, email.header.Header):
        value = str(value)
    value = _unsurrogate(str(value))
    # Unfold.
    value = re.sub(r"\r?\n[ \t]*", " ", value)
    if "=?" not in value:
        return clean_text(value)
    try:
        parts = email.header.decode_header(value)
    except Exception:
        return clean_text(value)
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            text, _ = decode_bytes(chunk, charset)
        else:
            text = chunk
        out.append(text)
    # decode_header drops whitespace between encoded words (correct), but
    # also between plain and encoded parts; rejoin sensibly.
    joined = ""
    for i, piece in enumerate(out):
        if i and parts[i - 1][1] is None and parts[i][1] is not None and joined and not joined.endswith(" "):
            joined += " "
        elif i and parts[i - 1][1] is not None and parts[i][1] is None and piece and not piece.startswith(" "):
            joined += " "
        joined += piece
    return clean_text(joined)


# --- Addresses ---------------------------------------------------------------

_ADDR_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)


def normalize_addr(addr: str) -> str:
    addr = clean_text(addr).strip("<>").strip()
    if "@" not in addr:
        return addr.lower()
    local, _, domain = addr.rpartition("@")
    domain = domain.strip().rstrip(".").lower()
    try:
        # Store IDNs as Unicode for display; rules look at the punycode form.
        if "xn--" in domain:
            domain = domain.encode("ascii").decode("idna")
    except (UnicodeError, ValueError):
        pass
    return f"{local}@{domain}".lower()


def parse_addresses(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    values = [_unsurrogate(str(v)) for v in raw]
    try:
        pairs = email.utils.getaddresses(values)
        if pairs and all(not a and not n for n, a in pairs):
            raise ValueError("strict parse failed")
    except Exception:
        try:
            pairs = email.utils.getaddresses(values, strict=False)
        except Exception:
            pairs = []
    result = []
    for name, addr in pairs:
        name = decode_header_value(name)
        if not addr or "@" not in addr:
            # Last resort: dig an address out of the raw text.
            found = _ADDR_RE.findall(name) if name else []
            if not found:
                continue
            addr = found[0]
            if name.strip("<> ") == addr:
                name = ""
        addr = normalize_addr(addr)
        if name.lower().strip("'\" ") == addr:
            name = ""
        result.append({"name": name.strip("'\" ")[:500], "addr": addr[:500]})
    # Fallback when the header was so broken getaddresses found nothing.
    if not result:
        for v in values:
            for a in _ADDR_RE.findall(decode_header_value(v)):
                result.append({"name": "", "addr": normalize_addr(a)})
    return result[:500]


# --- Misc header helpers -----------------------------------------------------

def parse_message_id(value) -> str:
    if not value:
        return ""
    value = _unsurrogate(str(value))
    m = _MSGID.search(value)
    if m:
        return m.group(1).strip()
    value = clean_text(value)
    return value[:900] if value and " " not in value else ""


def parse_references(value) -> list[str]:
    if not value:
        return []
    ids = _MSGID.findall(_unsurrogate(str(value)))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    # Huge threads: keep the root and the most recent ancestors.
    if len(out) > MAX_REFERENCES:
        out = out[:1] + out[-(MAX_REFERENCES - 1):]
    return out


def normalize_subject(subject: str) -> str:
    s = subject or ""
    for _ in range(20):
        new = _SUBJECT_PREFIX.sub("", s, count=1)
        if new == s:
            break
        s = new
    return clean_text(s).casefold()[:500]


def is_reply_subject(subject: str) -> bool:
    return bool(re.match(r"^\s*(re|aw|sv|vs|antw|r)\s*[:：]", subject or "", re.IGNORECASE))


def parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(_unsurrogate(str(value)))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt.year < 1980 or dt > now + timedelta(days=2):
        return None
    return dt.astimezone(timezone.utc)


# --- HTML to text ------------------------------------------------------------

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "table", "blockquote", "section", "article", "header", "footer", "hr", "pre"}
    SKIP = {"style", "script", "head", "title", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup[:MAX_HTML_BYTES])
        parser.close()
    except Exception:
        return clean_text(re.sub(r"<[^>]+>", " ", markup))
    text = "".join(parser.out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


class LinkExtractor(HTMLParser):
    """Collects (href, visible text) pairs for the link-mismatch risk rule."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._stack: list[list] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._stack.append([href, []])

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            href, text = self._stack.pop()
            if href and len(self.links) < 500:
                self.links.append((href.strip(), clean_text("".join(text))))

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][1].append(data)


def extract_links(markup: str) -> list[tuple[str, str]]:
    p = LinkExtractor()
    try:
        p.feed(markup[:MAX_HTML_BYTES])
        p.close()
    except Exception:
        pass
    return p.links


def text_to_html(text: str) -> str:
    return "<div style=\"white-space:pre-wrap\">" + html.escape(text) + "</div>"


# --- MIME structure ----------------------------------------------------------

@dataclass
class Part:
    index: int
    content_type: str
    disposition: str
    filename: str
    content_id: str
    charset: str | None
    obj: EmailMessage = field(repr=False)

    def payload(self) -> bytes:
        if self.content_type == "message/rfc822":
            try:
                inner = self.obj.get_payload()
                if isinstance(inner, list) and inner:
                    return inner[0].as_bytes()
                return self.obj.get_payload(decode=True) or b""
            except Exception:
                return b""
        try:
            data = self.obj.get_payload(decode=True)
        except Exception:
            data = None
        if data is None:
            raw = self.obj.get_payload()
            if isinstance(raw, str):
                data = raw.encode("utf-8", "surrogateescape")
            else:
                data = b""
        return data


def _safe_get(msg: EmailMessage, fn, default):
    try:
        return fn()
    except Exception:
        return default


def iter_leaf_parts(msg: EmailMessage):
    """Yield leaf parts depth-first, not descending into message/rfc822."""
    counter = [0]

    def walk(node, depth):
        if counter[0] >= MAX_PARTS:
            return
        ctype = _safe_get(node, node.get_content_type, "text/plain").lower()
        if depth < MAX_DEPTH and ctype.startswith("multipart/") and node.is_multipart():
            payload = _safe_get(node, node.get_payload, [])
            if isinstance(payload, list):
                for sub in payload:
                    if isinstance(sub, EmailMessage):
                        yield from walk(sub, depth + 1)
            return
        idx = counter[0]
        counter[0] += 1
        yield idx, node, ctype

    yield from walk(msg, 0)


def safe_filename(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", name).strip(" .")
    return name[:200]


def _filename(node: EmailMessage, idx: int, ctype: str) -> str:
    name = _safe_get(node, node.get_filename, None)
    if not name:
        name = _safe_get(node, lambda: node.get_param("name"), None)
        if isinstance(name, tuple):  # RFC 2231 tuple
            name = email.utils.collapse_rfc2231_value(name)
    name = safe_filename(decode_header_value(name) if name else "")
    if not name and ctype == "message/rfc822":
        # Name a forwarded message after its subject.
        inner = _safe_get(node, node.get_payload, None)
        if isinstance(inner, list) and inner and isinstance(inner[0], EmailMessage):
            subj = decode_header_value(_safe_get(inner[0], lambda: inner[0].get("Subject"), "") or "")
            name = safe_filename(subj[:80])
            if name:
                name += ".eml"
    if not name:
        ext = mimetypes.guess_extension(ctype) or (".eml" if ctype == "message/rfc822" else ".bin")
        name = f"attachment-{idx + 1}{ext}"
    return name[:200]


@dataclass
class ParsedMessage:
    message_id: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    subject: str = ""
    from_: list[dict] = field(default_factory=list)
    to: list[dict] = field(default_factory=list)
    cc: list[dict] = field(default_factory=list)
    bcc: list[dict] = field(default_factory=list)
    reply_to: list[dict] = field(default_factory=list)
    date: datetime | None = None
    text: str = ""
    html: str = ""
    attachments: list[Part] = field(default_factory=list)
    headers: dict = field(default_factory=dict)
    auth_results_raw: list[str] = field(default_factory=list)
    return_path: str = ""
    defects: list[str] = field(default_factory=list)
    msg: EmailMessage | None = field(default=None, repr=False)

    @property
    def from_addr(self) -> str:
        return self.from_[0]["addr"] if self.from_ else ""

    @property
    def from_name(self) -> str:
        return self.from_[0]["name"] if self.from_ else ""

    def links(self) -> list[tuple[str, str]]:
        return extract_links(self.html) if self.html else []

    @property
    def snippet(self) -> str:
        source = self.text or (html_to_text(self.html) if self.html else "")
        lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith(">")]
        return clean_text(" ".join(lines))[:280]


def parse_message(raw: bytes) -> ParsedMessage:
    pm = ParsedMessage()
    try:
        msg = email.message_from_bytes(raw, policy=compat32)
    except Exception as exc:  # pragma: no cover - the stdlib parser is lenient
        pm.defects.append(f"unparseable: {exc!r}")
        pm.text = decode_bytes(raw)[0][:MAX_TEXT_CHARS]
        return pm
    pm.msg = msg
    pm.defects.extend(type(d).__name__ for d in (msg.defects or [])[:20])

    # Raw header values (compat32 would turn raw 8-bit bytes into U+FFFD;
    # the raw values keep them as surrogate escapes we can recover).
    raw_headers = _safe_get(msg, lambda: list(msg.raw_items()), [])

    def get_all(name):
        low = name.lower()
        return [v for k, v in raw_headers if k.lower() == low]

    def get(name):
        values = get_all(name)
        return values[0] if values else None

    pm.message_id = parse_message_id(get("Message-ID"))
    irt = parse_references(get("In-Reply-To"))
    pm.in_reply_to = irt[-1] if irt else ""
    pm.references = parse_references(" ".join(_unsurrogate(str(v)) for v in get_all("References")))
    pm.subject = decode_header_value(get("Subject"))[:2000]
    pm.from_ = parse_addresses(get_all("From"))
    pm.to = parse_addresses(get_all("To"))
    pm.cc = parse_addresses(get_all("Cc"))
    pm.bcc = parse_addresses(get_all("Bcc"))
    pm.reply_to = parse_addresses(get_all("Reply-To"))
    pm.date = parse_date(get("Date"))
    rp = parse_addresses(get_all("Return-Path"))
    pm.return_path = rp[0]["addr"] if rp else ""
    pm.auth_results_raw = [decode_header_value(v) for v in get_all("Authentication-Results")][:20]
    for name in KEPT_HEADERS:
        v = get(name)
        if v is not None:
            pm.headers[name] = decode_header_value(v)[:2000]

    text_parts, html_parts = [], []
    for idx, node, ctype in iter_leaf_parts(msg):
        disp = (_safe_get(node, node.get_content_disposition, None) or "").lower()
        cid = parse_message_id(_safe_get(node, lambda: node.get("Content-ID"), None))
        charset = _safe_get(node, node.get_content_charset, None)
        has_name = bool(_safe_get(node, node.get_filename, None) or _safe_get(node, lambda: node.get_param("name"), None))
        is_body_text = (
            ctype in ("text/plain", "text/html")
            and disp != "attachment"
            and not (has_name and ctype == "text/plain")
        )
        if is_body_text:
            part = Part(idx, ctype, disp, "", cid, charset, node)
            (text_parts if ctype == "text/plain" else html_parts).append(part)
            continue
        if ctype.startswith("multipart/"):
            continue  # depth-limited container; ignore
        pm.attachments.append(
            Part(idx, ctype, disp or "attachment", _filename(node, idx, ctype), cid, charset, node)
        )

    def decode_part(part: Part) -> str:
        text, clean = decode_bytes(part.payload(), part.charset)
        if not clean:
            pm.defects.append(f"charset-fallback:{part.charset or 'none'}")
        return text

    if text_parts:
        pm.text = "\n\n".join(decode_part(p) for p in text_parts[:5])[:MAX_TEXT_CHARS]
    if html_parts:
        pm.html = decode_part(html_parts[0])[:MAX_HTML_BYTES]
    if not pm.text and pm.html:
        pm.text = html_to_text(pm.html)[:MAX_TEXT_CHARS]
    pm.text = pm.text.replace("\r\n", "\n").replace("\x00", "")
    return pm


def find_part(raw: bytes, index: int) -> Part | None:
    """Re-locate a leaf part by its index (used for attachment downloads)."""
    msg = email.message_from_bytes(raw, policy=compat32)
    for idx, node, ctype in iter_leaf_parts(msg):
        if idx == index:
            cid = parse_message_id(_safe_get(node, lambda: node.get("Content-ID"), None))
            return Part(idx, ctype, "", _filename(node, idx, ctype), cid,
                        _safe_get(node, node.get_content_charset, None), node)
    return None
