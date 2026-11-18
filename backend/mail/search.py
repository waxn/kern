"""Search with Gmail-like operators.

    from:alice  to:bob  cc:x  subject:invoice  in:inbox|sent|junk|trash|anywhere|<folder>
    label:work  has:attachment  is:unread|read|starred  risk:high|medium
    before:2024-01-31  after:2023-12-01  filename:pdf  "exact phrase"  -exclude

Free text uses SQLite FTS5 (mail/migrations/0002_fts.py) over subject,
sender, recipients, attachment names and body, with prefix matching on the
last word. User text never reaches the MATCH grammar raw: every word is
quoted, and the expression is passed as a query parameter.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone

from django.db.models import Q, QuerySet
from django.db.models.expressions import RawSQL

from .models import Folder, FolderRole, Label, Message

OPERATORS = {"from", "to", "cc", "subject", "in", "label", "has", "is", "before", "after", "risk", "filename"}


@dataclass
class ParsedQuery:
    words: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    negated: list[str] = field(default_factory=list)
    ops: list[tuple[str, str, bool]] = field(default_factory=list)  # (op, value, negated)

    @property
    def has_text(self) -> bool:
        return bool(self.words or self.phrases or self.negated)

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
    raw_tokens = re.findall(r'-?\w+:"[^"]*"|-?"[^"]*"|\S+', q or "")
    for tok in raw_tokens[:50]:
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
            if word:
                (pq.negated if neg else pq.words).append(word)
    return pq


def _date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _addr_q(prefix_fields: list[str], value: str) -> Q:
    q = Q()
    for f in prefix_fields:
        q |= Q(**{f"{f}__icontains": value})
    return q


def _folder_q(value: str) -> Q | None:
    v = value.lower()
    if v in ("anywhere", "all"):
        return None
    if v in ("starred",):
        return Q(flagged=True)
    role_map = {"inbox": FolderRole.INBOX, "sent": FolderRole.SENT, "drafts": FolderRole.DRAFTS,
                "junk": FolderRole.JUNK, "spam": FolderRole.JUNK, "trash": FolderRole.TRASH,
                "archive": FolderRole.ARCHIVE}
    if v in role_map:
        return Q(folder__role=role_map[v])
    folder = Folder.objects.filter(name__iexact=value).first()
    return Q(folder=folder) if folder else Q(pk__in=[])


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _fts_match(pq: ParsedQuery) -> str | None:
    """An FTS5 MATCH expression, or None when there's nothing positive to match."""
    pos = []
    words = [w for w in pq.words if re.search(r"\w", w)]
    for i, w in enumerate(words):
        last = i == len(words) - 1
        pos.append(_quote(w) + ("*" if last and len(re.sub(r"\W", "", w)) >= 2 else ""))
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
            cond = _addr_q(["from_addr", "from_name"], value)
        elif op == "to":
            cond = Q(search_recipients__icontains=value)
        elif op == "cc":
            cond = Q(search_recipients__icontains=value)
        elif op == "subject":
            cond = Q(subject__icontains=value)
        elif op == "in":
            scoped = True
            cond = _folder_q(value)
        elif op == "label":
            label = Label.objects.filter(name__iexact=value).first()
            cond = Q(labels=label) if label else Q(pk__in=[])
        elif op == "has" and value.lower() in ("attachment", "attachments"):
            cond = Q(has_attachments=True)
        elif op == "is":
            v = value.lower()
            cond = {"unread": Q(seen=False), "read": Q(seen=True), "starred": Q(flagged=True),
                    "flagged": Q(flagged=True), "answered": Q(answered=True)}.get(v)
        elif op == "before":
            d = _date(value)
            cond = Q(sort_date__lt=d) if d else None
        elif op == "after":
            d = _date(value)
            cond = Q(sort_date__gte=d) if d else None
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

