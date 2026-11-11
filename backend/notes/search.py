"""Full-text search on top of SQLite FTS5.

`search_fts(title, body)` rows share their rowid with `SearchEntry.id`, which
lets us update and delete index rows by primary key.
"""
import re

from django.db import connection

from .models import Block, Document, PropertyValue, SearchEntry, Tag
from .text import to_text

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)
HL_START, HL_END = "\x01", "\x02"


def _put(kind: str, ref_id, document_id, title: str, body: str) -> None:
    entry, _ = SearchEntry.objects.update_or_create(
        kind=kind, ref_id=str(ref_id), defaults={"document_id": document_id}
    )
    with connection.cursor() as cur:
        cur.execute("DELETE FROM search_fts WHERE rowid = %s", [entry.id])
        cur.execute(
            "INSERT INTO search_fts(rowid, title, body) VALUES (%s, %s, %s)",
            [entry.id, title, body],
        )


def remove(kind: str, ref_ids) -> None:
    ref_ids = [str(r) for r in ref_ids]
    for i in range(0, len(ref_ids), 500):
        chunk = ref_ids[i : i + 500]
        entries = SearchEntry.objects.filter(kind=kind, ref_id__in=chunk)
        rowids = list(entries.values_list("id", flat=True))
        if not rowids:
            continue
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM search_fts WHERE rowid IN (%s)" % ",".join(["%s"] * len(rowids)),
                rowids,
            )
        entries.delete()


def remove_document(document_id) -> None:
    """Drop every index row that belongs to a document (itself and its blocks)."""
    entries = SearchEntry.objects.filter(document_id=document_id)
    rowids = list(entries.values_list("id", flat=True))
    with connection.cursor() as cur:
        for i in range(0, len(rowids), 500):
            chunk = rowids[i : i + 500]
            cur.execute(
                "DELETE FROM search_fts WHERE rowid IN (%s)" % ",".join(["%s"] * len(chunk)),
                chunk,
            )
    entries.delete()


def _value_text(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return " ".join(_value_text(v) for v in value)
    return str(value)


def index_document(doc: Document) -> None:
    parts = [t.name for t in doc.tags.all()]
    for pv in PropertyValue.objects.filter(document=doc).select_related("definition"):
        d = pv.definition
        if d.type in ("select", "multi_select", "status"):
            names = {o.get("id"): o.get("name", "") for o in d.options or []}
            ids = pv.value if isinstance(pv.value, list) else [pv.value]
            text = " ".join(names.get(i, "") for i in ids)
        elif d.type == "relation":
            text = ""
        else:
            text = _value_text(pv.value)
        if text.strip():
            parts.append(f"{d.name}: {text}")
    _put("doc", doc.id, doc.id, doc.title, "\n".join(parts))


def block_text(block: Block) -> str:
    parts = [to_text(block.html)]
    props = block.props or {}
    for key in ("tex", "caption", "name", "url", "title"):
        if props.get(key):
            parts.append(str(props[key]))
    if block.type == "table":
        for row in props.get("rows") or []:
            parts.extend(to_text(c) for c in row)
    return "\n".join(p for p in parts if p.strip())


def index_block(block: Block) -> None:
    text = block_text(block)
    if text.strip():
        _put("block", block.id, block.document_id, "", text)
    else:
        remove("block", [block.id])


def index_tag(tag: Tag) -> None:
    _put("tag", tag.id, None, tag.name, "")


def build_match(query: str) -> str:
    words = _WORD_RE.findall(query or "")
    return " ".join(f'"{w}"*' for w in words[:12])


def search(query: str, kind: str | None = None, limit: int = 30, offset: int = 0):
    match = build_match(query)
    if not match:
        return [], {}
    base = """
        FROM search_fts
        JOIN notes_searchentry e ON e.id = search_fts.rowid
        LEFT JOIN notes_document d ON d.id = e.document_id
        WHERE search_fts MATCH %s AND (e.document_id IS NULL OR (d.trashed_at IS NULL AND d.is_template = 0))
    """
    with connection.cursor() as cur:
        cur.execute(f"SELECT e.kind, COUNT(*) {base} GROUP BY e.kind", [match])
        counts = dict(cur.fetchall())
        params = [HL_START, HL_END, HL_START, HL_END, match]
        kind_sql = ""
        if kind:
            kind_sql = " AND e.kind = %s"
            params.append(kind)
        params += [limit, offset]
        cur.execute(
            f"""
            SELECT e.kind, e.ref_id, e.document_id,
                   highlight(search_fts, 0, %s, %s),
                   snippet(search_fts, 1, %s, %s, '…', 18)
            {base}{kind_sql}
            ORDER BY bm25(search_fts, 8.0, 1.0), d.updated_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()
    return rows, counts


def reindex_all() -> int:
    with connection.cursor() as cur:
        cur.execute("DELETE FROM search_fts")
    SearchEntry.objects.all().delete()
    n = 0
    for doc in Document.objects.filter(is_template=False).prefetch_related("tags"):
        index_document(doc)
        n += 1
    for block in Block.objects.filter(document__is_template=False).iterator():
        index_block(block)
        n += 1
    for tag in Tag.objects.all():
        index_tag(tag)
        n += 1
    from . import learning, tasks
    from .models import CardNote, Task
    for note in CardNote.objects.filter(active=True):
        learning.index_note(note)
        n += 1
    for t in Task.objects.all():
        tasks.index_task(t)
        n += 1
    return n
