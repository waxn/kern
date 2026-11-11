import mimetypes
import threading
import os
import re
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from kern import tenancy
from django.db.models import Count, Max, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from . import search
from . import dbcompute, learning, tasks, versions
from .models import (
    Attachment, Block, Card, Database, DbView, Document, Link, PropertyDef, PropertyValue, Setting,
    Tag, Task,
)
from .text import extract_refs, one_line, sanitize

# Block types whose `html` is plain text (stored HTML-escaped).
BLOCK_TYPES = {
    "paragraph", "h1", "h2", "h3", "bullet", "numbered", "todo", "toggle",
    "quote", "callout", "divider", "code", "equation", "table",
    "image", "video", "audio", "file", "bookmark", "embed", "synced", "database",
}


class BadRequest(Exception):
    pass


def bad(msg, status=400):
    return Response({"detail": msg}, status=status)


def as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise Http404


def get_doc(doc_id, include_trashed=True) -> Document:
    try:
        doc = Document.objects.get(id=as_uuid(doc_id))
    except Document.DoesNotExist:
        raise Http404
    if doc.trashed_at and not include_trashed:
        raise Http404
    return doc


# ---------------------------------------------------------------- serializers


def doc_json(doc: Document, tag_ids=None) -> dict:
    return {
        "id": str(doc.id),
        "parent": str(doc.parent_id) if doc.parent_id else None,
        "title": doc.title,
        "icon": doc.icon,
        "cover": doc.cover,
        "position": doc.position,
        "is_favorite": doc.is_favorite,
        "is_archived": doc.is_archived,
        "trashed_at": doc.trashed_at,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "last_opened_at": doc.last_opened_at,
        "entry_of": str(doc.entry_of_id) if doc.entry_of_id else None,
        "database": db_id_of(doc),
        "is_template": doc.is_template,
        "kind": doc.kind,
        "template_tag": str(doc.template_tag_id) if doc.template_tag_id else None,
        "template_db": str(doc.template_db_id) if doc.template_db_id else None,
        "tags": tag_ids
        if tag_ids is not None
        else [str(t) for t in doc.tags.values_list("id", flat=True)],
    }


_local = threading.local()  # per-request scratch space (requests run on separate threads)


def db_id_of(doc: Document):
    """Database id if this document is a database's page."""
    pages = getattr(_local, "db_pages", None)
    if pages is not None:
        return pages.get(doc.id)
    db = Database.objects.filter(page_id=doc.id).values_list("id", flat=True).first()
    return str(db) if db else None


def block_json(b: Block) -> dict:
    return {
        "id": str(b.id),
        "parent": str(b.parent_id) if b.parent_id else None,
        "position": b.position,
        "type": b.type,
        "html": b.html,
        "props": b.props or {},
        "collapsed": b.collapsed,
    }


def tag_json(tag: Tag, doc_count=None) -> dict:
    data = {"id": str(tag.id), "name": tag.name, "color": tag.color}
    if doc_count is not None:
        data["doc_count"] = doc_count
    return data


def prop_json(d: PropertyDef) -> dict:
    return {
        "id": str(d.id),
        "tag": str(d.tag_id) if d.tag_id else None,
        "name": d.name,
        "type": d.type,
        "options": d.options or [],
        "config": d.config or {},
        "database": str(d.database_id) if d.database_id else None,
        "position": d.position,
    }


def resolve_refs(pairs) -> dict:
    """Resolve (kind, id) pairs to display info. Missing targets are omitted."""
    by_kind: dict[str, set] = {"doc": set(), "block": set(), "tag": set()}
    for kind, ref in pairs:
        try:
            by_kind[kind].add(uuid.UUID(ref))
        except (KeyError, ValueError):
            continue
    out = {}
    for d in Document.objects.filter(id__in=by_kind["doc"]):
        out[f"doc:{d.id}"] = {"title": d.title, "icon": d.icon, "trashed": bool(d.trashed_at)}
    for b in Block.objects.filter(id__in=by_kind["block"]).select_related("document"):
        out[f"block:{b.id}"] = {
            "title": one_line(b.html, 120) or search.block_text(b)[:120],
            "doc": str(b.document_id),
            "doc_title": b.document.title,
            "trashed": bool(b.document.trashed_at),
        }
    for t in Tag.objects.filter(id__in=by_kind["tag"]):
        out[f"tag:{t.id}"] = {"title": t.name, "color": t.color}
    return out


def doc_properties(doc: Document, tag_ids) -> dict:
    values = {str(pv.definition_id): pv.value for pv in doc.property_values.all()}
    query = Q(tag_id__in=tag_ids) | Q(id__in=[uuid.UUID(k) for k in values])
    if doc.entry_of_id:
        query |= Q(database_id=doc.entry_of_id)
    defs = list(PropertyDef.objects.filter(query).distinct().order_by("database_id", "position"))
    # Database properties first, then tag properties.
    defs.sort(key=lambda d: (0 if d.database_id else 1, d.position))
    if any(d.type in PropertyDef.COMPUTED or d.type == "relation" for d in defs):
        values = dbcompute.compute([doc], defs)[doc.id]
    hidden = set()
    if doc.entry_of_id:
        hidden = {str(d.id) for d in defs if d.database_id and (d.config or {}).get("hidden_in_page")}
    return {"defs": [prop_json(d) for d in defs if str(d.id) not in hidden], "values": values}


def document_payload(doc: Document) -> dict:
    tag_ids = [str(t) for t in doc.tags.values_list("id", flat=True)]
    blocks = list(doc.blocks.order_by("position", "created_at"))
    block_ids = [str(b.id) for b in blocks]
    pairs = set(
        Link.objects.filter(source_document=doc).values_list("target_kind", "target_id")
    )
    counts = dict(
        Link.objects.filter(target_kind="block", target_id__in=block_ids)
        .values_list("target_id")
        .annotate(n=Count("id"))
    )
    props = doc_properties(doc, tag_ids)
    for d in props["defs"]:
        if d["type"] == "relation":
            for ref in props["values"].get(d["id"]) or []:
                pairs.add(("doc", ref))
    return {
        "document": doc_json(doc, tag_ids),
        "blocks": [block_json(b) for b in blocks],
        "refs": resolve_refs(pairs),
        "properties": props,
        "block_backlinks": counts,
        "block_cards": block_card_counts(doc),
        "block_tasks": {
            str(t.block_id): {"id": str(t.id), "due": t.due.isoformat() if t.due else None,
                              "priority": t.priority, "recurrence": t.recurrence, "done": t.done}
            for t in Task.objects.filter(block__document=doc)
        },
        "version": blocks_version(doc),
        "card_count": Card.objects.filter(note__document=doc, note__active=True, suspended=False).count(),
        "backlink_count": Link.objects.filter(target_kind="doc", target_id=str(doc.id))
        .exclude(source_document=doc)
        .exclude(source_document__trashed_at__isnull=False)
        .count(),
    }


# ------------------------------------------------------------------ documents


def subtree_ids(root_id) -> list:
    """A document, its descendants, and the entries of any database among them."""
    ids, frontier = [root_id], [root_id]
    while frontier:
        dbs = Database.objects.filter(page_id__in=frontier).values_list("id", flat=True)
        frontier = list(
            Document.objects.filter(Q(parent_id__in=frontier) | Q(entry_of_id__in=list(dbs)))
            .exclude(id__in=ids)
            .values_list("id", flat=True)
        )
        ids.extend(frontier)
    return ids


def next_position(parent_id) -> float:
    top = Document.objects.filter(
        parent_id=parent_id, trashed_at__isnull=True, entry_of__isnull=True
    ).aggregate(
        m=Max("position")
    )["m"]
    return (top or 0) + 1


@api_view(["GET"])
def tree(request):
    if not getattr(request, "_testing", False) and not os.environ.get("KERN_NO_AUTO_BACKUP"):
        from . import backup
        backup.maybe_auto_backup()
    docs = Document.objects.filter(trashed_at__isnull=True, is_template=False).order_by(
        "position", "created_at"
    )
    _local.db_pages = {p: str(d) for d, p in Database.objects.values_list("id", "page_id")}
    # Sweep blank pages abandoned for over an hour (e.g. tab closed mid-"New page").
    stale = timezone.now() - timedelta(hours=1)
    for d in docs.filter(title="", kind="page", created_at__lt=stale, entry_of__isnull=True):
        if (d.last_opened_at or d.created_at) < stale and is_blank_page(d):
            purge_doc(d)
    docs = docs.all()
    tags_by_doc: dict = {}
    for doc_id, tag_id in Document.tags.through.objects.values_list("document_id", "tag_id"):
        tags_by_doc.setdefault(doc_id, []).append(str(tag_id))
    has_content = set(
        Block.objects.exclude(html="").exclude(html__isnull=True).values_list("document_id", flat=True)
    ) | set(
        Block.objects.exclude(type__in=["paragraph", "bullet", "numbered", "todo", "quote"])
        .values_list("document_id", flat=True)
    )
    has_children = set(Document.objects.filter(parent__isnull=False).values_list("parent_id", flat=True))
    try:
        out = []
        for d in docs:
            j = doc_json(d, tags_by_doc.get(d.id, []))
            # A page nobody has typed anything into: hidden from Recent / Home.
            j["empty"] = (
                d.kind == "page" and not d.title.strip() and not d.icon and not d.cover
                and not j["tags"] and not j["database"] and not d.entry_of_id
                and d.id not in has_content and d.id not in has_children
            )
            out.append(j)
        return Response(out)
    finally:
        _local.db_pages = None


@api_view(["POST"])
def document_create(request):
    data = request.data
    parent = get_doc(data["parent"], include_trashed=False) if data.get("parent") else None
    if data.get("template"):
        tpl = get_doc(data["template"])
        with tenancy.atomic():
            doc = instantiate_template(tpl, parent)
        return Response(doc_json(doc), status=201)
    kwargs = {}
    if data.get("id"):
        kwargs["id"] = as_uuid(data["id"])
    with tenancy.atomic():
        doc = Document.objects.create(
            parent=parent,
            title=str(data.get("title", ""))[:500],
            icon=str(data.get("icon", ""))[:64],
            position=next_position(parent.id if parent else None),
            last_opened_at=timezone.now(),
            kind="group" if data.get("kind") == "group" else "page",
            **kwargs,
        )
        search.index_document(doc)
    return Response(doc_json(doc, []), status=201)


def is_blank_page(doc: Document) -> bool:
    """An untitled page nobody has typed anything into."""
    if doc.kind != "page" or doc.title.strip() or doc.icon or doc.cover or doc.entry_of_id:
        return False
    if doc.tags.exists() or doc.children.exists() or db_id_of(doc):
        return False
    for html, typ in doc.blocks.values_list("html", "type"):
        if typ not in ("paragraph", "bullet", "numbered", "todo", "quote") or re.sub(
            r"<[^>]*>|&nbsp;", "", html or ""
        ).strip():
            return False
    return True


def purge_doc(doc: Document):
    with tenancy.atomic():
        ids = subtree_ids(doc.id)
        for did in ids:
            search.remove_document(did)
        scrub_relations(ids)
        doc.delete()


@api_view(["POST"])
def document_discard(request, doc_id):
    """Permanently drop a page that was never written in (no-op otherwise)."""
    doc = get_doc(doc_id)
    if is_blank_page(doc):
        purge_doc(doc)
        return Response({"discarded": True})
    return Response({"discarded": False})


@api_view(["GET", "PATCH", "DELETE"])
def document_detail(request, doc_id):
    doc = get_doc(doc_id)
    if request.method == "GET":
        if not doc.trashed_at:
            Document.objects.filter(id=doc.id).update(last_opened_at=timezone.now())
            doc.last_opened_at = timezone.now()
        return Response(document_payload(doc))

    if request.method == "DELETE":
        # Permanent deletion; only allowed from the trash.
        if not doc.trashed_at:
            return bad("Move the document to the trash first.", 409)
        with tenancy.atomic():
            ids = subtree_ids(doc.id)
            for did in ids:
                search.remove_document(did)
            scrub_relations(ids)
            orphan_tasks = list(Task.objects.filter(document_id__in=ids))
            doc.delete()
            for t in orphan_tasks:
                t.refresh_from_db()
                tasks.index_task(t)
        return Response(status=204)

    data = request.data
    with tenancy.atomic():
        fields = []
        for name, limit in (("title", 500), ("icon", 64), ("cover", 500)):
            if name in data:
                setattr(doc, name, str(data[name] or "")[:limit])
                fields.append(name)
        for name in ("is_favorite", "is_archived"):
            if name in data:
                setattr(doc, name, bool(data[name]))
                fields.append(name)
        if data.get("kind") in ("page", "group"):
            doc.kind = data["kind"]
            fields.append("kind")
        if fields:
            if {"title", "icon", "cover"} & set(fields):
                doc.updated_at = timezone.now()
                fields.append("updated_at")
            doc.save(update_fields=fields)
        applied = []
        if "tags" in data:
            before = set(doc.tags.values_list("id", flat=True))
            tags = list(Tag.objects.filter(id__in=[as_uuid(t) for t in data["tags"]]))
            doc.tags.set(tags)
            if not doc.is_template:
                for tag in tags:
                    if tag.id not in before:
                        applied += apply_tag_templates(doc, tag)
        if "title" in data or "tags" in data:
            search.index_document(doc)
    out = doc_json(doc)
    out["templates_applied"] = applied
    return Response(out)


@api_view(["POST"])
def document_move(request, doc_id):
    doc = get_doc(doc_id, include_trashed=False)
    if doc.entry_of_id:
        return bad("Database entries live in their database and cannot be moved.")
    parent_id = request.data.get("parent")
    parent = get_doc(parent_id, include_trashed=False) if parent_id else None
    if parent and parent.id in set(subtree_ids(doc.id)):
        return bad("A page cannot be moved inside itself.")
    with tenancy.atomic():
        siblings = list(
            Document.objects.filter(parent=parent, trashed_at__isnull=True, entry_of__isnull=True)
            .exclude(id=doc.id)
            .order_by("position", "created_at")
        )
        index = request.data.get("index")
        index = len(siblings) if index is None else max(0, min(int(index), len(siblings)))
        siblings.insert(index, doc)
        doc.parent = parent
        for i, d in enumerate(siblings):
            d.position = float(i + 1)
        Document.objects.bulk_update(siblings, ["parent", "position"])
    return Response(
        {"moved": str(doc.id), "order": [str(d.id) for d in siblings]}
    )


def copy_document(src: Document, parent, title=None, as_template=None, entry_of="same") -> Document:
    dst = Document.objects.create(
        parent=parent,
        title=title if title is not None else src.title,
        icon=src.icon,
        cover=src.cover,
        position=next_position(parent.id if parent else None)
        if title is not None
        else src.position,
        entry_of_id=src.entry_of_id if entry_of == "same" else entry_of,
        is_template=src.is_template if as_template is None else as_template,
        template_tag_id=src.template_tag_id if as_template is not False else None,
        template_db_id=src.template_db_id if as_template is not False else None,
    )
    dst.tags.set(src.tags.all())
    PropertyValue.objects.bulk_create(
        PropertyValue(document=dst, definition_id=pv.definition_id, value=pv.value)
        for pv in src.property_values.all()
    )
    blocks = list(src.blocks.all())
    ids = {b.id: uuid.uuid4() for b in blocks}
    new_blocks = [
        Block(
            id=ids[b.id], document=dst, parent_id=ids.get(b.parent_id), position=b.position,
            type=b.type, html=b.html, props=b.props, collapsed=b.collapsed,
        )
        for b in blocks
    ]
    Block.objects.bulk_create(new_blocks)
    reindex_blocks(dst, new_blocks)
    if dst.is_template:
        search.remove_document(dst.id)
    else:
        search.index_document(dst)
    if hasattr(src, "database"):
        from .views_db import duplicate_database
        duplicate_database(src.database, dst)
    for child in src.children.filter(trashed_at__isnull=True):
        copy_document(child, dst)
    return dst


def instantiate_template(tpl: Document, parent, entry_of=None) -> Document:
    """Create a real document from a template (title, icon, tags, properties, blocks)."""
    doc = copy_document(tpl, parent, title=tpl.title, as_template=False, entry_of=entry_of)
    doc.last_opened_at = timezone.now()
    doc.save(update_fields=["last_opened_at"])
    return doc


def apply_tag_templates(doc: Document, tag: Tag) -> list:
    """Insert the structure of templates bound to `tag` at the end of `doc`."""
    applied = []
    for tpl in Document.objects.filter(is_template=True, template_tag=tag, trashed_at__isnull=True):
        blocks = list(tpl.blocks.all())
        if blocks:
            top = doc.blocks.filter(parent__isnull=True).aggregate(m=Max("position"))["m"] or 0
            ids = {b.id: uuid.uuid4() for b in blocks}
            new = [
                Block(
                    id=ids[b.id], document=doc, parent_id=ids.get(b.parent_id),
                    position=b.position + (top if b.parent_id is None else 0),
                    type=b.type, html=b.html, props=b.props, collapsed=b.collapsed,
                )
                for b in blocks
            ]
            Block.objects.bulk_create(new)
            reindex_blocks(doc, new)
        have = set(doc.property_values.values_list("definition_id", flat=True))
        PropertyValue.objects.bulk_create(
            PropertyValue(document=doc, definition_id=pv.definition_id, value=pv.value)
            for pv in tpl.property_values.all()
            if pv.definition_id not in have and pv.value not in (None, "", [])
        )
        if not doc.icon and tpl.icon:
            doc.icon = tpl.icon
            doc.save(update_fields=["icon"])
        applied.append(str(tpl.id))
    return applied


def scrub_relations(doc_ids) -> None:
    """Remove deleted documents from relation values so relations stay valid."""
    gone = {str(i) for i in doc_ids}
    for pv in PropertyValue.objects.filter(definition__type="relation").exclude(
        document_id__in=doc_ids
    ):
        if isinstance(pv.value, list) and gone & set(pv.value):
            pv.value = [v for v in pv.value if v not in gone] or None
            pv.save(update_fields=["value"])


@api_view(["POST"])
def document_duplicate(request, doc_id):
    src = get_doc(doc_id, include_trashed=False)
    with tenancy.atomic():
        dst = copy_document(src, src.parent, title=(src.title or "Untitled") + " (copy)")
        if src.entry_of_id:
            dst.position = src.position
            dst.save(update_fields=["position"])
    return Response(doc_json(dst), status=201)


@api_view(["POST"])
def document_trash(request, doc_id):
    doc = get_doc(doc_id)
    now = timezone.now()
    ids = subtree_ids(doc.id)
    Document.objects.filter(id__in=ids, trashed_at__isnull=True).update(trashed_at=now)
    return Response({"trashed": [str(i) for i in ids]})


@api_view(["POST"])
def document_restore(request, doc_id):
    doc = get_doc(doc_id)
    if not doc.trashed_at:
        return Response(doc_json(doc))
    with tenancy.atomic():
        ids = subtree_ids(doc.id)
        Document.objects.filter(id__in=ids, trashed_at=doc.trashed_at).update(trashed_at=None)
        doc.refresh_from_db()
        if doc.entry_of_id and doc.entry_of.page.trashed_at:
            # Restoring an entry of a trashed database brings the database back too.
            page = doc.entry_of.page
            Document.objects.filter(id__in=subtree_ids(page.id), trashed_at=page.trashed_at).update(
                trashed_at=None
            )
        if doc.parent_id and doc.parent.trashed_at:
            doc.parent = None
            doc.position = next_position(None)
            doc.save(update_fields=["parent", "position"])
    return Response(doc_json(doc))


@api_view(["GET"])
def trash_list(request):
    docs = Document.objects.filter(trashed_at__isnull=False).select_related(
        "parent", "entry_of__page"
    )
    roots = [
        d for d in docs
        if (not d.parent_id or not d.parent.trashed_at)
        and (not d.entry_of_id or not d.entry_of.page.trashed_at)
    ]
    roots.sort(key=lambda d: d.trashed_at, reverse=True)
    return Response([doc_json(d, []) for d in roots])


# --------------------------------------------------------------------- blocks


def reindex_blocks(doc: Document, blocks) -> None:
    """Refresh links and the search index for the given blocks."""
    ids = [b.id for b in blocks]
    Link.objects.filter(source_block_id__in=ids).delete()
    links = []
    for b in blocks:
        sources = [b.html]
        if b.type == "table":
            sources += [c for row in (b.props or {}).get("rows") or [] for c in row]
        refs = set()
        for s in sources:
            refs |= extract_refs(s)
        if b.type == "embed":
            p = b.props or {}
            if p.get("kind") in ("doc", "block") and p.get("target"):
                refs.add((p["kind"], str(p["target"]).lower()))
        for kind, ref in refs:
            try:
                ref = str(uuid.UUID(ref))
            except ValueError:
                continue
            links.append(
                Link(source_block=b, source_document=doc, target_kind=kind, target_id=ref)
            )
        search.index_block(b)
    Link.objects.bulk_create(links)


def block_subtree_ids(ids) -> list:
    out, frontier = list(ids), list(ids)
    while frontier:
        frontier = list(Block.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        out.extend(frontier)
    return out


def clean_props(block_type: str, props) -> dict:
    if not isinstance(props, dict):
        return {}
    if block_type == "table" and isinstance(props.get("rows"), list):
        props = dict(props)
        props["rows"] = [
            [sanitize(str(c)) for c in row] for row in props["rows"] if isinstance(row, list)
        ]
    return props


class Conflict(Exception):
    def __init__(self, ids):
        self.ids = ids


def blocks_version(doc: Document):
    from django.db.models import Max as _Max
    v = doc.blocks.aggregate(m=_Max("updated_at"))["m"]
    return max(v, doc.updated_at) if v else doc.updated_at


def apply_block_sync(doc: Document, upserts, deletes, base=None) -> None:
    ids = [as_uuid(u["id"]) for u in upserts]
    existing = {b.id: b for b in Block.objects.filter(id__in=ids)}
    if base is not None:
        # Refuse to overwrite blocks someone else changed after this client last saw them.
        touched = set(ids) | {as_uuid(d) for d in deletes}
        clash = [
            str(b) for b in Block.objects.filter(document=doc, id__in=touched, updated_at__gt=base)
            .values_list("id", flat=True)
        ]
        if clash:
            raise Conflict(clash)
    versions.maybe_snapshot(doc)
    created, updated = [], []
    now = timezone.now()
    for u, bid in zip(upserts, ids):
        b = existing.get(bid)
        is_new = b is None
        if is_new:
            b = Block(id=bid)
        btype = str(u.get("type", "paragraph"))
        if btype not in BLOCK_TYPES:
            raise BadRequest(f"Unknown block type: {btype}")
        b.document = doc
        b.parent_id = as_uuid(u["parent"]) if u.get("parent") else None
        b.position = float(u.get("position", 0))
        b.type = btype
        b.html = sanitize(str(u.get("html", "")))
        b.props = clean_props(btype, u.get("props"))
        b.collapsed = bool(u.get("collapsed", False))
        b.updated_at = now
        (created if is_new else updated).append(b)
    Block.objects.bulk_create(created)
    Block.objects.bulk_update(
        updated, ["document", "parent", "position", "type", "html", "props", "collapsed", "updated_at"]
    )

    # Structural validation: parents must live in this document, no cycles.
    parents = dict(Block.objects.filter(document=doc).values_list("id", "parent_id"))
    for bid in ids:
        seen, cur = set(), bid
        while cur is not None:
            if cur in seen:
                raise BadRequest("Block hierarchy contains a cycle.")
            seen.add(cur)
            if cur not in parents:
                raise BadRequest("Block parent is missing or in another document.")
            cur = parents[cur]

    if deletes:
        del_ids = [as_uuid(d) for d in deletes]
        roots = list(
            Block.objects.filter(document=doc, id__in=del_ids).values_list("id", flat=True)
        )
        all_ids = block_subtree_ids(roots)
        search.remove("block", all_ids)
        learning.deactivate_blocks(all_ids)
        Block.objects.filter(id__in=roots).delete()
        gone = set(all_ids)
        created = [b for b in created if b.id not in gone]
        updated = [b for b in updated if b.id not in gone]

    reindex_blocks(doc, created + updated)
    learning.sync_blocks(doc, [b.id for b in created + updated])
    patched = tasks.sync_blocks(doc, created + updated)
    doc.updated_at = now
    doc.save(update_fields=["updated_at"])
    return patched


@api_view(["POST"])
def blocks_sync(request, doc_id):
    doc = get_doc(doc_id)
    upserts = request.data.get("upserts") or []
    deletes = request.data.get("deletes") or []
    base = None
    if request.data.get("base") and not request.data.get("force"):
        from django.utils.dateparse import parse_datetime
        base = parse_datetime(str(request.data["base"]))
    try:
        with tenancy.atomic():
            patched = apply_block_sync(doc, upserts, deletes, base)
    except Conflict as c:
        current = Block.objects.filter(id__in=c.ids)
        return Response({
            "detail": "This page was changed elsewhere since you last loaded it.",
            "conflict": c.ids, "blocks": [block_json(b) for b in current],
            "version": blocks_version(doc),
        }, status=409)
    except BadRequest as e:
        return bad(str(e))
    except IntegrityError:
        return bad("Block references a parent that does not exist.")
    return Response({
        "ok": True, "updated_at": doc.updated_at, "version": blocks_version(doc),
        "patched": [block_json(b) for b in patched],
        "block_cards": block_card_counts(doc),
    })


def block_card_counts(doc: Document) -> dict:
    counts: dict = {}
    for ref in Card.objects.filter(note__document=doc, note__active=True).exclude(
        note__block_ref=""
    ).values_list("note__block_ref", flat=True):
        counts[ref] = counts.get(ref, 0) + 1
    return counts


# ------------------------------------------------------------------ backlinks


def backlinks_payload(links) -> list:
    links = (
        links.filter(source_document__trashed_at__isnull=True)
        .select_related("source_block", "source_block__parent", "source_document")
        .order_by("-source_document__updated_at", "source_block__position")
    )
    groups: dict = {}
    seen = set()
    for link in links:
        b, d = link.source_block, link.source_document
        if b.id in seen:
            continue
        seen.add(b.id)
        g = groups.setdefault(
            d.id, {"doc": {"id": str(d.id), "title": d.title, "icon": d.icon}, "items": []}
        )
        g["items"].append(
            {
                "block": str(b.id),
                "type": b.type,
                "html": b.html,
                "context": one_line(b.parent.html, 90) if b.parent_id else "",
            }
        )
    return list(groups.values())


@api_view(["GET"])
def document_backlinks(request, doc_id):
    doc = get_doc(doc_id)
    links = Link.objects.filter(target_kind="doc", target_id=str(doc.id)).exclude(
        source_document=doc
    )
    return Response(backlinks_payload(links))


@api_view(["GET"])
def block_backlinks(request, block_id):
    links = Link.objects.filter(target_kind="block", target_id=str(as_uuid(block_id)))
    return Response(backlinks_payload(links))


@api_view(["GET"])
def refs_resolve(request):
    pairs = []
    for item in request.query_params.get("ids", "").split(","):
        kind, _, ref = item.partition(":")
        if ref:
            pairs.append((kind, ref))
    return Response(resolve_refs(pairs))


# ----------------------------------------------------------------------- tags


@api_view(["GET", "POST"])
def tags(request):
    if request.method == "GET":
        qs = Tag.objects.annotate(n=Count("documents", filter=Q(documents__trashed_at__isnull=True)))
        return Response([tag_json(t, t.n) for t in qs])
    name = str(request.data.get("name", "")).strip().lstrip("#")[:120]
    if not name:
        return bad("Tag name is required.")
    existing = Tag.objects.filter(key=name.lower()).first()
    if existing:
        return Response(tag_json(existing, existing.documents.count()))
    try:
        with tenancy.atomic():
            tag = Tag.objects.create(name=name, color=str(request.data.get("color", ""))[:24])
            search.index_tag(tag)
    except IntegrityError:
        # Created by a concurrent request a moment ago.
        tag = Tag.objects.get(key=name.lower())
        return Response(tag_json(tag, tag.documents.count()))
    return Response(tag_json(tag, 0), status=201)


def get_tag(tag_id) -> Tag:
    try:
        return Tag.objects.get(id=as_uuid(tag_id))
    except Tag.DoesNotExist:
        raise Http404


@api_view(["GET", "PATCH", "DELETE"])
def tag_detail(request, tag_id):
    tag = get_tag(tag_id)
    if request.method == "GET":
        docs = tag.documents.filter(trashed_at__isnull=True).order_by("-updated_at")
        links = Link.objects.filter(target_kind="tag", target_id=str(tag.id))
        return Response(
            {
                "tag": tag_json(tag, len(docs)),
                "properties": [prop_json(d) for d in tag.properties.all()],
                "documents": [doc_json(d) for d in docs],
                "blocks": backlinks_payload(links),
            }
        )
    if request.method == "DELETE":
        with tenancy.atomic():
            search.remove("tag", [tag.id])
            docs = list(tag.documents.all())
            tag.delete()
            for d in docs:
                search.index_document(d)
        return Response(status=204)
    data = request.data
    with tenancy.atomic():
        if "name" in data:
            name = str(data["name"]).strip().lstrip("#")[:120]
            if not name:
                return bad("Tag name is required.")
            if Tag.objects.filter(key=name.lower()).exclude(id=tag.id).exists():
                return bad("A tag with that name already exists.", 409)
            tag.name = name
        if "color" in data:
            tag.color = str(data["color"] or "")[:24]
        tag.save()
        search.index_tag(tag)
        for d in tag.documents.all():
            search.index_document(d)
    return Response(tag_json(tag))


# ----------------------------------------------------------------- properties


@api_view(["GET", "POST"])
def properties(request):
    if request.method == "GET":
        return Response([prop_json(d) for d in PropertyDef.objects.all()])
    data = request.data
    ptype = data.get("type", "text")
    if ptype not in PropertyDef.TYPES:
        return bad("Unknown property type.")
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        return bad("Property name is required.")
    tag = get_tag(data["tag"]) if data.get("tag") else None
    if data.get("database"):
        from .views_db import create_db_property, get_db
        with tenancy.atomic():
            d = create_db_property(get_db(data["database"]), data)
        return Response(prop_json(d), status=201)
    top = PropertyDef.objects.filter(tag=tag).aggregate(m=Max("position"))["m"] or 0
    d = PropertyDef.objects.create(
        tag=tag, name=name, type=ptype, options=data.get("options") or [], position=top + 1,
        config=data.get("config") or {},
    )
    return Response(prop_json(d), status=201)


def get_prop(prop_id) -> PropertyDef:
    try:
        return PropertyDef.objects.get(id=as_uuid(prop_id))
    except PropertyDef.DoesNotExist:
        raise Http404


@api_view(["PATCH", "DELETE"])
def property_detail(request, prop_id):
    d = get_prop(prop_id)
    if request.method == "DELETE":
        with tenancy.atomic():
            docs = list(Document.objects.filter(property_values__definition=d))
            unlink_reverse(d)
            d.delete()
            for doc in docs:
                search.index_document(doc)
        return Response(status=204)
    data = request.data
    if "name" in data and str(data["name"]).strip():
        d.name = str(data["name"]).strip()[:120]
    if "options" in data and isinstance(data["options"], list):
        d.options = data["options"]
    if "position" in data:
        d.position = float(data["position"])
    with tenancy.atomic():
        if "type" in data and data["type"] in PropertyDef.TYPES and data["type"] != d.type:
            if d.type == "relation":
                unlink_reverse(d)
                d.config = {}
            d.type = data["type"]
            d.values.all().delete()  # values of the old type are meaningless
            if d.type == "relation" and d.database_id:
                from .views_db import link_relation
                d.save()
                link_relation(d, (data.get("config") or {}))
        if "config" in data and isinstance(data["config"], dict) and d.type != "relation":
            d.config = {**(d.config or {}), **data["config"]}
        elif "config" in data and isinstance(data["config"], dict):
            # Relation targets are fixed once created; only display flags may change.
            d.config = {**(d.config or {}), **{k: v for k, v in data["config"].items()
                                              if k not in ("target", "reverse")}}
        d.save()
    return Response(prop_json(d))


def unlink_reverse(d: PropertyDef) -> None:
    """Turn the other side of a two-way relation into a one-way relation."""
    if d.type != "relation":
        return
    rev = (d.config or {}).get("reverse")
    if rev:
        other = PropertyDef.objects.filter(id=rev).first()
        if other and other.id != d.id:
            other.config = {**(other.config or {}), "reverse": None}
            other.save(update_fields=["config"])


def coerce_value(d: PropertyDef, value):
    if value is None or value == "":
        return None
    t = d.type
    try:
        if t == "number":
            return float(value) if not isinstance(value, bool) else None
        if t == "boolean":
            return bool(value)
        if t == "rating":
            return max(0, min(5, int(value)))
        if t in ("multi_select", "relation"):
            items = value if isinstance(value, list) else [value]
            return list(dict.fromkeys(str(v) for v in items)) or None
        if t in PropertyDef.COMPUTED:
            raise BadRequest("This property is calculated and cannot be edited.")
        return str(value)[:10000]
    except (TypeError, ValueError):
        raise BadRequest("Invalid value for this property type.")


@api_view(["PUT", "DELETE"])
def document_property(request, doc_id, prop_id):
    doc = get_doc(doc_id)
    d = get_prop(prop_id)
    with tenancy.atomic():
        if request.method == "DELETE":
            PropertyValue.objects.filter(document=doc, definition=d).delete()
        else:
            try:
                value = coerce_value(d, request.data.get("value"))
            except BadRequest as e:
                return bad(str(e))
            if d.type == "relation":
                from .views_db import sync_reverse
                old = PropertyValue.objects.filter(document=doc, definition=d).values_list(
                    "value", flat=True
                ).first() or []
                target_db = (d.config or {}).get("target")
                if target_db and value:
                    allowed = set(
                        str(i) for i in Document.objects.filter(
                            entry_of_id=target_db, id__in=value
                        ).values_list("id", flat=True)
                    )
                    value = [v for v in value if v in allowed] or None
                sync_reverse(d, doc, set(old or []), set(value or []))
            PropertyValue.objects.update_or_create(
                document=doc, definition=d, defaults={"value": value}
            )
        search.index_document(doc)
        Document.objects.filter(id=doc.id).update(updated_at=timezone.now())
    tag_ids = [str(t) for t in doc.tags.values_list("id", flat=True)]
    return Response(doc_properties(doc, tag_ids))


# --------------------------------------------------------------------- search


def doc_paths(doc_ids) -> dict:
    """Map document id -> list of ancestor titles (root first)."""
    info = {
        d[0]: d for d in Document.objects.values_list("id", "parent_id", "title", "icon")
    }
    out = {}
    for did in doc_ids:
        path, cur, guard = [], info.get(did), 0
        cur = info.get(cur[1]) if cur else None
        while cur and guard < 50:
            path.append(cur[2] or "Untitled")
            cur = info.get(cur[1])
            guard += 1
        out[did] = list(reversed(path))
    return out, info


@api_view(["GET"])
def search_view(request):
    q = request.query_params.get("q", "")
    kind = request.query_params.get("kind") or None
    limit = min(int(request.query_params.get("limit", 30)), 100)
    offset = int(request.query_params.get("offset", 0))
    rows, counts = search.search(q, kind, limit, offset)
    doc_ids = {uuid.UUID(r[2]) for r in rows if r[2]}
    paths, info = doc_paths(doc_ids)
    tag_ids = [r[1] for r in rows if r[0] == "tag"]
    tag_map = {str(t.id): t for t in Tag.objects.filter(id__in=tag_ids)}
    results = []
    for kind_, ref_id, doc_hex, title_hl, snippet in rows:
        item = {"kind": kind_, "id": ref_id, "title": title_hl, "snippet": snippet}
        if doc_hex:
            did = uuid.UUID(doc_hex)
            d = info.get(did)
            item.update(
                doc=str(did),
                doc_title=(d[2] if d else ""),
                icon=(d[3] if d else ""),
                path=paths.get(did, []),
            )
        if kind_ == "tag":
            t = tag_map.get(ref_id)
            if not t:
                continue
            item["color"] = t.color
        results.append(item)
    return Response({"results": results, "counts": counts})


@api_view(["GET"])
def suggest(request):
    """Autocomplete for [[ references, # tags and (( block references."""
    q = request.query_params.get("q", "").strip()
    kinds = set(request.query_params.get("kinds", "doc,tag").split(","))
    limit = min(int(request.query_params.get("limit", 8)), 30)
    out = []
    if "doc" in kinds:
        qs = Document.objects.filter(trashed_at__isnull=True, is_template=False)
        if q:
            starts = list(qs.filter(title__istartswith=q).order_by("-last_opened_at")[:limit])
            rest = list(
                qs.filter(title__icontains=q)
                .exclude(id__in=[d.id for d in starts])
                .order_by("-last_opened_at")[: limit - len(starts)]
            )
            docs = starts + rest
        else:
            docs = list(qs.order_by("-last_opened_at")[:limit])
        paths, _ = doc_paths([d.id for d in docs])
        out += [
            {"kind": "doc", "id": str(d.id), "title": d.title, "icon": d.icon,
             "path": paths.get(d.id, [])}
            for d in docs
        ]
    if "tag" in kinds:
        qs = Tag.objects.all()
        if q:
            qs = qs.filter(key__contains=q.lower())
        out += [
            {"kind": "tag", "id": str(t.id), "title": t.name, "color": t.color}
            for t in qs[:limit]
        ]
    if "block" in kinds and q:
        rows, _ = search.search(q, "block", limit, 0)
        blocks = {
            str(b.id): b
            for b in Block.objects.filter(id__in=[r[1] for r in rows]).select_related("document")
        }
        for r in rows:
            b = blocks.get(r[1])
            if b:
                out.append(
                    {"kind": "block", "id": str(b.id), "title": one_line(b.html, 120),
                     "doc": str(b.document_id), "doc_title": b.document.title}
                )
    return Response(out)


# --------------------------------------------------------- settings and files


@api_view(["GET", "PATCH"])
def settings_view(request):
    private = {"ai", "ai_secret", "git_auth"}  # managed by /api/ai/config and /api/git/config; secrets never leave the server
    if request.method == "PATCH":
        if not isinstance(request.data, dict):
            return bad("Expected an object.")
        for key, value in request.data.items():
            if str(key) in private:
                continue
            Setting.objects.update_or_create(key=str(key)[:120], defaults={"value": value})
    return Response({s.key: s.value for s in Setting.objects.exclude(key__in=private)})


def attachment_json(a: Attachment) -> dict:
    return {
        "id": str(a.id), "url": a.file.url, "name": a.name, "mime": a.mime,
        "size": a.size, "created_at": a.created_at,
    }


@api_view(["POST"])
@parser_classes([MultiPartParser])
def file_upload(request):
    f = request.FILES.get("file")
    if not f:
        return bad("No file provided.")
    mime = f.content_type or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    a = Attachment(name=f.name[:255], mime=mime[:127], size=f.size)
    ext = "".join(c for c in (f.name.rsplit(".", 1)[-1] if "." in f.name else "") if c.isalnum())
    a.file.save(f"{a.id}.{ext.lower()}" if ext else str(a.id), f, save=True)
    return Response(attachment_json(a), status=201)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Health check endpoint. Signed-out callers (the container health check) only learn "ok"."""
    user = request.user
    if not (user and user.is_authenticated):
        return Response({"ok": True})
    result = {"ok": True, "version": "1.0"}

    # Check yt-dlp availability for web archiving
    try:
        import yt_dlp
        result["yt_dlp"] = yt_dlp.version.__version__
    except ImportError:
        result["yt_dlp"] = None
    
    return Response(result)
