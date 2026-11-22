"""Mail search: Gmail's operators and then some.

    from:alice  from:me  to:bob  to:me  cc:x  bcc:x  subject:invoice  domain:example.com  list:news
    in:inbox|sent|drafts|junk|trash|archive|anywhere|<folder>   label:work
    has:attachment|pdf|image|document|spreadsheet|presentation|archive|calendar|link
    is:unread|read|starred|answered|snoozed|muted   risk:high|medium   filename:pdf
    before:2024-01-31  after:2023-12  older_than:2w  newer_than:3d  (d, w, m, y)
    larger:5M  smaller:200K
    "exact phrase"   -exclude   word OR other

Free text uses SQLite FTS5 (mail/migrations/0002_fts.py) over subject, sender, recipients,
attachment names and body, with prefix matching (``invo`` finds invoices) and diacritics
folded. Results can be ordered by date or by relevance (bm25 with a boost for recent mail),
and each hit carries a snippet of where it matched.

User text never reaches the MATCH grammar raw: every word is quoted, and the expression is
passed as a query parameter.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from django.db.models import Q, QuerySet
from django.db.models.expressions import RawSQL
from django.utils import timezone as djtz

from kern import tenancy

from .models import Correspondent, Folder, FolderRole, Label, Message

OPERATORS = {"from", "to", "cc", "bcc", "subject", "in", "label", "has", "is", "before", "after", "risk",
             "filename", "older_than", "newer_than", "larger", "smaller", "domain", "list"}

# has:<kind> -> attachment file name endings.
FILE_KINDS = {
    "pdf": (".pdf",),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff", ".svg"),
    "document": (".doc", ".docx", ".odt", ".rtf", ".pages", ".txt", ".md"),
    "spreadsheet": (".xls", ".xlsx", ".ods", ".csv", ".numbers"),
    "presentation": (".ppt", ".pptx", ".odp", ".key"),
    "archive": (".zip", ".rar", ".7z", ".tar", ".gz"),
    "calendar": (".ics",),
    "audio": (".mp3", ".m4a", ".wav", ".ogg", ".flac"),
    "video": (".mp4", ".mov", ".webm", ".mkv", ".avi"),
}
FILE_KINDS["images"] = FILE_KINDS["image"]
FILE_KINDS["invite"] = FILE_KINDS["calendar"]

# Column weights for bm25: subject, from_name, from_addr, recipients, attachment names, body.
BM25 = "bm25(mail_message_fts, 8.0, 5.0, 5.0, 2.0, 4.0, 1.0)"
HIT_START, HIT_END = "\x02", "\x03"


@dataclass
class ParsedQuery:
    words: list[str] = field(default_factory=list)
    any_of: list[list[str]] = field(default_factory=list)  # word OR word OR word
    phrases: list[str] = field(default_factory=list)
    negated: list[str] = field(default_factory=list)
    ops: list[tuple[str, str, bool]] = field(default_factory=list)  # (op, value, negated)

    @property
    def has_text(self) -> bool:
        return bool(self.words or self.any_of or self.phrases or self.negated)

    def op_values(self, name: str) -> list[str]:
        return [v for o, v, neg in self.ops if o == name and not neg]


def _tokens(q: str) -> list[str]:
    try:
        lex = shlex.shlex(q, posix=True)
        lex.whitespace_split = True
        lex.quotes = '"'
        lex.commenters = ""
        return list(lex)
    except ValueError:  # unbalanced quotes
        return q.replace('"', " ").split()


def parse(q: str) -> ParsedQuery:
    pq = ParsedQuery()
    raw_tokens = re.findall(r'-?\w+:"[^"]*"|-?"[^"]*"|\S+', q or "")[:50]
    plain: list[str] = []  # positive free words in order, "OR" kept, to group afterwards
    for tok in raw_tokens:
        neg = tok.startswith("-") and len(tok) > 1
        body = tok[1:] if neg else tok
        m = re.match(r"^(\w+):(.*)$", body)
        if m and m.group(1).lower() in OPERATORS and m.group(2):
            pq.ops.append((m.group(1).lower(), m.group(2).strip('"'), neg))
            continue
        if body.startswith('"') and body.endswith('"') and len(body) > 2:
            (pq.negated if neg else pq.phrases).append(body.strip('"'))
            continue
        for word in _tokens(body):
            if not word:
                continue
            if neg:
                pq.negated.append(word)
            else:
                plain.append(word)
    # "a OR b OR c" (upper case, like Gmail) is one either/or group; a stray OR is a word.
    i = 0
    while i < len(plain):
        group = [plain[i]]
        while i + 2 < len(plain) and plain[i + 1] == "OR" and plain[i + 2] != "OR":
            group.append(plain[i + 2])
            i += 2
        if len(group) > 1:
            pq.any_of.append(group)
        else:
            pq.words.append(group[0])
        i += 1
    return pq


def _date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m", "%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    span = _span(value)
    return djtz.now() - span if span else None


def _span(value: str) -> timedelta | None:
    m = re.fullmatch(r"(\d{1,4})\s*([dwmy])", value.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    return timedelta(days=n * {"d": 1, "w": 7, "m": 30, "y": 365}[m.group(2)])


def _size(value: str) -> int | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg]?)b?", value.strip().lower())
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)])


def _me() -> list[str]:
    from .identity import my_addresses

    return sorted(my_addresses())


def _addr_q(prefix_fields: list[str], value: str) -> Q:
    q = Q()
    for f in prefix_fields:
        q |= Q(**{f"{f}__icontains": value})
    return q


def _from_q(value: str) -> Q:
    if value.lower() == "me":
        return Q(from_addr__in=_me())
    return _addr_q(["from_addr", "from_name"], value)


def _to_q(value: str) -> Q:
    if value.lower() == "me":
        q = Q()
        for a in _me():
            q |= Q(search_recipients__icontains=a)
        return q if _me() else Q(pk__in=[])
    return Q(search_recipients__icontains=value)


def _folder_q(value: str) -> Q | None:
    v = value.lower()
    if v in ("anywhere", "all"):
        return None
    if v in ("starred",):
        return Q(flagged=True)
    role_map = {"inbox": FolderRole.INBOX, "sent": FolderRole.SENT, "drafts": FolderRole.DRAFTS,
                "junk": FolderRole.JUNK, "spam": FolderRole.JUNK, "trash": FolderRole.TRASH,
                "archive": FolderRole.ARCHIVE, "snoozed": FolderRole.SNOOZED}
    if v in role_map:
        return Q(folder__role=role_map[v])
    folder = Folder.objects.filter(name__iexact=value).first() or Folder.objects.filter(name__iendswith="/" + value).first()
    return Q(folder=folder) if folder else Q(pk__in=[])


def _has_q(value: str) -> Q | None:
    v = value.lower()
    if v in ("attachment", "attachments", "file", "files"):
        return Q(has_attachments=True)
    if v in FILE_KINDS:
        q = Q()
        for ext in FILE_KINDS[v]:
            q |= Q(attachment_names__icontains=ext)
        return q & Q(has_attachments=True)
    if v in ("link", "links"):
        return Q(body_text__icontains="http")
    if v in ("star", "stars"):
        return Q(flagged=True)
    return None


def _is_q(value: str) -> Q | None:
    v = value.lower()
    simple = {"unread": Q(seen=False), "read": Q(seen=True), "starred": Q(flagged=True),
              "flagged": Q(flagged=True), "answered": Q(answered=True), "replied": Q(answered=True),
              "draft": Q(is_draft=True)}
    if v in simple:
        return simple[v]
    if v == "snoozed":
        from .models import Snooze, SnoozeStatus

        ids = list(Snooze.objects.filter(status=SnoozeStatus.ACTIVE, thread__isnull=False).values_list("thread_id", flat=True))
        return Q(thread_id__in=ids)
    if v == "muted":
        from .models import Mute

        ids = list(Mute.objects.filter(thread__isnull=False).values_list("thread_id", flat=True))
        return Q(thread_id__in=ids)
    return None


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _term(w: str, prefix: bool) -> str:
    core = re.sub(r"\W", "", w)
    return _quote(w) + ("*" if prefix and len(core) >= 2 else "")


def _fts_match(pq: ParsedQuery) -> str | None:
    """An FTS5 MATCH expression, or None when there's nothing positive to match."""
    pos = []
    words = [w for w in pq.words if re.search(r"\w", w)]
    for i, w in enumerate(words):
        # Every word matches as a prefix ("invo" finds invoice); short words only when typed last.
        pos.append(_term(w, len(re.sub(r"\W", "", w)) >= 3 or i == len(words) - 1))
    for group in pq.any_of:
        alts = [_term(w, True) for w in group if re.search(r"\w", w)]
        if alts:
            pos.append("(" + " OR ".join(alts) + ")")
    pos += [_quote(p) for p in pq.phrases if re.search(r"\w", p)]
    if not pos:
        return None
    expr = " AND ".join(pos)
    neg = [_quote(n) for n in pq.negated if re.search(r"\w", n)]
    if neg:
        expr = f"({expr}) NOT ({' OR '.join(neg)})"
    return expr


def message_queryset(q: str) -> QuerySet:
    pq = parse(q)
    qs = Message.objects.all()
    scoped = False
    for op, value, neg in pq.ops:
        cond = None
        if op == "from":
            cond = _from_q(value)
        elif op in ("to", "cc", "bcc"):
            cond = _to_q(value)
        elif op == "subject":
            cond = Q(subject__icontains=value)
        elif op == "in":
            scoped = True
            cond = _folder_q(value)
        elif op == "label":
            label = Label.objects.filter(name__iexact=value).first() or Label.objects.filter(name__istartswith=value).first()
            cond = Q(labels=label) if label else Q(pk__in=[])
        elif op == "has":
            cond = _has_q(value)
        elif op == "is":
            cond = _is_q(value)
        elif op == "before":
            d = _date(value)
            cond = Q(sort_date__lt=d) if d else None
        elif op == "after":
            d = _date(value)
            cond = Q(sort_date__gte=d) if d else None
        elif op in ("older_than", "newer_than"):
            span = _span(value)
            if span:
                cond = Q(sort_date__lt=djtz.now() - span) if op == "older_than" else Q(sort_date__gte=djtz.now() - span)
        elif op in ("larger", "smaller"):
            n = _size(value)
            if n is not None:
                cond = Q(size__gte=n) if op == "larger" else Q(size__lt=n)
        elif op == "domain":
            d = value.lower().lstrip("@")
            cond = Q(from_addr__iendswith="@" + d) | Q(from_addr__iendswith="." + d)
        elif op == "list":
            cond = Q(**{"headers__list-id__icontains": value})
        elif op == "risk":
            levels = {"high": ["high"], "medium": ["medium", "high"]}.get(value.lower())
            cond = Q(risk_level__in=levels) if levels else None
        elif op == "filename":
            cond = Q(attachment_names__icontains=value)
        if cond is not None:
            qs = qs.exclude(cond) if neg else qs.filter(cond)
    if not scoped:
        qs = qs.exclude(folder__role__in=[FolderRole.TRASH, FolderRole.JUNK])

    if pq.has_text:
        expr = _fts_match(pq)
        if expr:
            qs = qs.filter(id__in=RawSQL("SELECT rowid FROM mail_message_fts WHERE mail_message_fts MATCH %s", [expr]))
        else:  # only exclusions: "-newsletter"
            for w in pq.negated:
                qs = qs.exclude(Q(subject__icontains=w) | Q(body_text__icontains=w))
    return qs


def thread_ids_for(q: str):
    return message_queryset(q).values("thread_id")


# --- relevance and snippets ----------------------------------------------------------

RANK_POOL = 5000


def ranked_thread_ids(q: str, limit: int = 2000) -> list[int] | None:
    """Thread ids, best match first (bm25, recent mail boosted), or None when the query has no
    words to rank by (then date order is the only sensible one)."""
    pq = parse(q)
    expr = _fts_match(pq)
    if not expr:
        return None
    with tenancy.conn().cursor() as c:
        c.execute(f"SELECT rowid, {BM25} FROM mail_message_fts WHERE mail_message_fts MATCH %s ORDER BY 2 LIMIT {RANK_POOL}",
                  [expr])
        ranks = dict(c.fetchall())
    if not ranks:
        return []
    now = djtz.now()
    best: dict[int, float] = {}
    rows = message_queryset(q).filter(id__in=list(ranks), thread__isnull=False).values_list("id", "thread_id", "sort_date")
    for mid, tid, when in rows:
        age = max(0.0, (now - when).total_seconds() / 86400) if when else 3650
        score = -ranks[mid] * (1 + 1 / (1 + age / 30))  # up to twice as relevant when fresh
        if score > best.get(tid, float("-inf")):
            best[tid] = score
    return sorted(best, key=lambda t: -best[t])[:limit]


def hits(q: str, thread_ids: list[int]) -> dict[int, str]:
    """thread id -> a short excerpt around the best match, with HIT_START/HIT_END around matched words."""
    expr = _fts_match(parse(q))
    if not expr or not thread_ids:
        return {}
    msg_thread = dict(Message.objects.filter(thread_id__in=thread_ids).values_list("id", "thread_id")[:5000])
    if not msg_thread:
        return {}
    marks = ",".join("%s" for _ in msg_thread)
    with tenancy.conn().cursor() as c:
        c.execute(
            f"SELECT rowid, snippet(mail_message_fts, 5, %s, %s, '…', 16), {BM25} FROM mail_message_fts "
            f"WHERE mail_message_fts MATCH %s AND rowid IN ({marks}) ORDER BY 3",
            [HIT_START, HIT_END, expr, *msg_thread],
        )
        out: dict[int, str] = {}
        for mid, snip, _ in c.fetchall():
            tid = msg_thread.get(mid)
            if tid and tid not in out and snip and HIT_START in snip:
                out[tid] = re.sub(r"\s+", " ", snip).strip()[:400]
    return out


# --- suggestions while typing ------------------------------------------------------------


def last_token(q: str) -> tuple[str, str]:
    """(operator or "", partial value) of what's being typed at the end of q."""
    tail = (q or "").rsplit(" ", 1)[-1] if q and not q.endswith(" ") else ""
    m = re.match(r"^-?(\w+):(.*)$", tail)
    if m and m.group(1).lower() in OPERATORS:
        return m.group(1).lower(), m.group(2).strip('"')
    return "", tail.strip('"')


def contacts(prefix: str, limit: int = 5) -> list[dict]:
    if len(prefix) < 1:
        return []
    qs = Correspondent.objects.filter(Q(address__icontains=prefix) | Q(name__icontains=prefix))
    rows = sorted(qs[:200], key=lambda c: (-(c.sent_count * 3 + c.received_count), c.address))[:limit]
    return [{"name": c.name, "addr": c.address, "count": c.sent_count + c.received_count} for c in rows]
