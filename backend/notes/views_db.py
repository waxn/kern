"""Databases, their views and entries; templates; the knowledge graph."""
import json
import uuid

from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import dbcompute, search
from .models import Block, Database, DbView, Document, Link, PropertyDef, PropertyValue, Tag
from .views import (
    BadRequest, as_uuid, bad, copy_document, doc_json, get_doc, instantiate_template,
    next_position, prop_json, subtree_ids,
)

STATUS_OPTIONS = [
    {"id": "not-started", "name": "Not started", "color": "gray", "group": "todo"},
    {"id": "in-progress", "name": "In progress", "color": "blue", "group": "in_progress"},
    {"id": "done", "name": "Done", "color": "green", "group": "done"},
]
ROLLUP_FNS = {
    "show", "count", "count_values", "count_unique", "count_empty", "count_not_empty",
    "percent_empty", "percent_not_empty", "sum", "average", "median", "min", "max", "range",
    "checked", "unchecked", "percent_checked", "earliest", "latest",
}


def get_db(db_id) -> Database:
    try:
        return Database.objects.select_related("page").get(id=as_uuid(db_id))
    except Database.DoesNotExist:
        raise Http404


def view_json(v: DbView) -> dict:
    return {
        "id": str(v.id), "name": v.name, "type": v.type, "config": v.config or {},
        "position": v.position,
    }


def db_json(db: Database) -> dict:
    p = db.page
    return {
        "id": str(db.id), "page": str(p.id), "title": p.title, "icon": p.icon,
        "trashed": bool(p.trashed_at),
    }


def row_json(doc: Document, values: dict) -> dict:
    return {
        "id": str(doc.id), "title": doc.title, "icon": doc.icon, "cover": doc.cover,
        "position": doc.position, "created_at": doc.created_at, "updated_at": doc.updated_at,
        "values": values,
    }


def db_payload(db: Database) -> dict:
    defs = list(db.properties.order_by("position"))
    rows = list(
        db.entries.filter(trashed_at__isnull=True, is_template=False).order_by("position", "created_at")
    )
    values = dbcompute.compute(rows, defs) if rows else {}
    templates = Document.objects.filter(is_template=True, template_db=db, trashed_at__isnull=True)
    return {
        "database": db_json(db),
        "properties": [prop_json(d) for d in defs],
        "views": [view_json(v) for v in db.views.all()],
        "rows": [row_json(r, values.get(r.id, {})) for r in rows],
        "templates": [{"id": str(t.id), "title": t.title, "icon": t.icon} for t in templates],
    }


# ------------------------------------------------------------- properties


def link_relation(d: PropertyDef, cfg: dict) -> None:
    """Configure a relation property; two-way relations get a reverse property."""
    target = cfg.get("target")
    target_db = get_db(target) if target else None
    d.config = {"target": str(target_db.id) if target_db else None, "reverse": None}
    d.save(update_fields=["config"])
    if target_db and cfg.get("two_way", True):
        src_title = d.database.page.title if d.database_id else "Related"
        top = target_db.properties.aggregate(m=Max("position"))["m"] or 0
        rev = PropertyDef.objects.create(
            database=target_db, name=(cfg.get("reverse_name") or src_title or "Related")[:120],
            type="relation", position=top + 1,
            config={"target": str(d.database_id) if d.database_id else None, "reverse": str(d.id)},
        )
        d.config["reverse"] = str(rev.id)
        d.save(update_fields=["config"])


def create_db_property(db: Database, data: dict) -> PropertyDef:
    ptype = data.get("type", "text")
    if ptype not in PropertyDef.TYPES:
        raise BadRequest("Unknown property type.")
    name = str(data.get("name", "")).strip()[:120] or ptype.replace("_", " ").capitalize()
    top = db.properties.aggregate(m=Max("position"))["m"] or 0
    options = data.get("options") or ([dict(o) for o in STATUS_OPTIONS] if ptype == "status" else [])
    cfg = data.get("config") or {}
    d = PropertyDef.objects.create(
        database=db, name=name, type=ptype, options=options, position=top + 1,
        config={} if ptype == "relation" else clean_config(ptype, cfg),
    )
    if ptype == "relation":
        link_relation(d, cfg)
    return d


def clean_config(ptype: str, cfg: dict) -> dict:
    if ptype == "rollup":
        fn = cfg.get("fn") if cfg.get("fn") in ROLLUP_FNS else "count"
        return {"relation": cfg.get("relation"), "target": cfg.get("target") or "title", "fn": fn}
    if ptype == "formula":
        return {"expr": str(cfg.get("expr", ""))[:4000]}
    return {k: v for k, v in cfg.items() if k in ("format", "hidden_in_page")}


def sync_reverse(d: PropertyDef, doc: Document, old: set, new: set) -> None:
    """Mirror a relation change onto the other side of a two-way relation."""
    rev_id = (d.config or {}).get("reverse")
    if not rev_id:
        return
    rev = PropertyDef.objects.filter(id=rev_id).first()
    if not rev:
        return
    me = str(doc.id)
    for target_id, add in [(t, True) for t in new - old] + [(t, False) for t in old - new]:
        try:
            tid = uuid.UUID(target_id)
        except ValueError:
            continue
        if not Document.objects.filter(id=tid).exists():
            continue
        pv, _ = PropertyValue.objects.get_or_create(document_id=tid, definition=rev)
        cur = list(pv.value or [])
        if add and me not in cur:
            cur.append(me)
        if not add and me in cur:
            cur.remove(me)
        pv.value = cur or None
        pv.save(update_fields=["value"])


# --------------------------------------------------------------- endpoints


@api_view(["GET", "POST"])
def databases(request):
    if request.method == "GET":
        dbs = Database.objects.select_related("page").filter(page__trashed_at__isnull=True)
        return Response([db_json(db) for db in dbs.order_by("page__title")])
    data = request.data
    parent = get_doc(data["parent"], include_trashed=False) if data.get("parent") else None
    with transaction.atomic():
        page = Document.objects.create(
            parent=parent, title=str(data.get("title", ""))[:500], icon=str(data.get("icon", ""))[:64],
            position=next_position(parent.id if parent else None), last_opened_at=timezone.now(),
        )
        db = Database.objects.create(page=page)
        if data.get("preset") == "kanban":
            # A board: cards grouped by status, each card a page you can write in.
            status = PropertyDef.objects.create(
                database=db, name="Status", type="status", position=1,
                options=[
                    {"id": "todo", "name": "To do", "color": "gray", "group": "todo"},
                    {"id": "doing", "name": "Doing", "color": "blue", "group": "in_progress"},
                    {"id": "done", "name": "Done", "color": "green", "group": "done"},
                ],
            )
            PropertyDef.objects.create(database=db, name="Tags", type="multi_select", position=2)
            PropertyDef.objects.create(database=db, name="Due", type="date", position=3)
            DbView.objects.create(database=db, name="Board", type="board", position=1,
                                  config={"group_by": str(status.id)})
            DbView.objects.create(database=db, name="Table", type="table", position=2)
            if not page.title:
                page.title, page.icon = "Kanban board", page.icon or "📋"
                page.save(update_fields=["title", "icon"])
        else:
            PropertyDef.objects.create(database=db, name="Tags", type="multi_select", position=1)
            DbView.objects.create(database=db, name="Table", type="table", position=1)
        search.index_document(page)
    return Response(db_payload(db), status=201)


@api_view(["GET"])
def database_detail(request, db_id):
    return Response(db_payload(get_db(db_id)))


@api_view(["POST"])
def db_property_order(request, db_id):
    db = get_db(db_id)
    order = [str(x) for x in request.data.get("order") or []]
    with transaction.atomic():
        for i, pid in enumerate(order):
            db.properties.filter(id=as_uuid(pid)).update(position=i + 1)
    return Response({"ok": True})


@api_view(["POST"])
def db_entries(request, db_id):
    db = get_db(db_id)
    data = request.data
    with transaction.atomic():
        if data.get("template"):
            doc = instantiate_template(get_doc(data["template"]), None, entry_of=db.id)
            if data.get("title"):
                doc.title = str(data["title"])[:500]
                doc.save(update_fields=["title"])
        else:
            doc = Document.objects.create(
                entry_of=db, title=str(data.get("title", ""))[:500],
                icon=str(data.get("icon", ""))[:64],
            )
        top = db.entries.exclude(id=doc.id).aggregate(m=Max("position"))["m"] or 0
        doc.position = top + 1
        doc.save(update_fields=["position"])
        defs = {str(d.id): d for d in db.properties.all()}
        from .views import coerce_value

        for pid, value in (data.get("values") or {}).items():
            d = defs.get(pid)
            if not d or d.type in PropertyDef.COMPUTED:
                continue
            try:
                v = coerce_value(d, value)
            except BadRequest:
                continue
            PropertyValue.objects.update_or_create(document=doc, definition=d, defaults={"value": v})
            if d.type == "relation":
                sync_reverse(d, doc, set(), set(v or []))
        search.index_document(doc)
    return Response(doc_json(doc), status=201)


@api_view(["POST"])
def db_entries_trash(request, db_id):
    db = get_db(db_id)
    ids = [as_uuid(i) for i in request.data.get("ids") or []]
    now = timezone.now()
    trashed = []
    for doc in db.entries.filter(id__in=ids, trashed_at__isnull=True):
        sub = subtree_ids(doc.id)
        Document.objects.filter(id__in=sub, trashed_at__isnull=True).update(trashed_at=now)
        trashed += [str(i) for i in sub]
    return Response({"trashed": trashed})


@api_view(["POST"])
def db_views(request, db_id):
    db = get_db(db_id)
    vtype = request.data.get("type", "table")
    if vtype not in DbView.TYPES:
        return bad("Unknown view type.")
    top = db.views.aggregate(m=Max("position"))["m"] or 0
    v = DbView.objects.create(
        database=db, type=vtype, name=str(request.data.get("name") or vtype.capitalize())[:120],
        config=request.data.get("config") or {}, position=top + 1,
    )
    return Response(view_json(v), status=201)


@api_view(["PATCH", "DELETE"])
def view_detail(request, view_id):
    try:
        v = DbView.objects.get(id=as_uuid(view_id))
    except DbView.DoesNotExist:
        raise Http404
    if request.method == "DELETE":
        if v.database.views.count() <= 1:
            return bad("A database needs at least one view.")
        v.delete()
        return Response(status=204)
    data = request.data
    if "name" in data:
        v.name = str(data["name"] or v.type.capitalize())[:120]
    if data.get("type") in DbView.TYPES:
        v.type = data["type"]
    if isinstance(data.get("config"), dict):
        v.config = data["config"]
    if "position" in data:
        v.position = float(data["position"])
    v.save()
    return Response(view_json(v))


def duplicate_database(src: Database, page: Document) -> None:
    """Copy a database (properties, views, entries) onto a freshly copied page."""
    db = Database.objects.create(page=page)
    idmap: dict[str, str] = {str(src.id): str(db.id)}
    old_defs = list(src.properties.all())
    for d in old_defs:
        idmap[str(d.id)] = str(uuid.uuid4())
    entries = list(src.entries.filter(trashed_at__isnull=True, is_template=False))
    for e in entries:
        idmap[str(e.id)] = str(uuid.uuid4())

    def remap(value):
        text = json.dumps(value)
        for a, b in idmap.items():
            text = text.replace(a, b)
        return json.loads(text)

    for d in old_defs:
        cfg = dict(d.config or {})
        if d.type == "relation":
            # Relations to itself stay internal; relations elsewhere become one-way.
            if cfg.get("target") != str(src.id):
                cfg["reverse"] = None
        PropertyDef.objects.create(
            id=idmap[str(d.id)], database=db, name=d.name, type=d.type, options=d.options,
            position=d.position, config=remap(cfg),
        )
    for v in src.views.all():
        DbView.objects.create(database=db, name=v.name, type=v.type, position=v.position,
                              config=remap(v.config or {}))
    for e in entries:
        new = Document.objects.create(
            id=idmap[str(e.id)], entry_of=db, title=e.title, icon=e.icon, cover=e.cover,
            position=e.position,
        )
        new.tags.set(e.tags.all())
        for pv in e.property_values.all():
            def_id = idmap.get(str(pv.definition_id), str(pv.definition_id))
            PropertyValue.objects.create(document=new, definition_id=def_id, value=remap(pv.value))
        blocks = list(e.blocks.all())
        bmap = {b.id: uuid.uuid4() for b in blocks}
        Block.objects.bulk_create(
            Block(id=bmap[b.id], document=new, parent_id=bmap.get(b.parent_id), position=b.position,
                  type=b.type, html=b.html, props=b.props, collapsed=b.collapsed)
            for b in blocks
        )
        from .views import reindex_blocks
        reindex_blocks(new, list(new.blocks.all()))
        search.index_document(new)


# -------------------------------------------------------------- templates


def template_json(t: Document) -> dict:
    data = doc_json(t, [str(x) for x in t.tags.values_list("id", flat=True)])
    data["block_count"] = t.blocks.count()
    return data


@api_view(["GET", "POST"])
def templates(request):
    if request.method == "GET":
        qs = Document.objects.filter(is_template=True, trashed_at__isnull=True).order_by("title")
        return Response([template_json(t) for t in qs])
    data = request.data
    with transaction.atomic():
        if data.get("from"):
            # Save an existing page as a template.
            src = get_doc(data["from"], include_trashed=False)
            t = copy_document(src, None, title=src.title or "Untitled template", as_template=True,
                              entry_of=src.entry_of_id)
            t.template_db_id = src.entry_of_id
            t.save(update_fields=["template_db"])
        else:
            t = Document.objects.create(
                is_template=True, title=str(data.get("title") or "Untitled template")[:500],
                icon=str(data.get("icon", ""))[:64],
            )
        apply_template_binding(t, data)
    return Response(template_json(t), status=201)


def apply_template_binding(t: Document, data: dict) -> None:
    fields = []
    if "template_tag" in data:
        t.template_tag = Tag.objects.filter(id=as_uuid(data["template_tag"])).first() if data["template_tag"] else None
        fields.append("template_tag")
    if "template_db" in data:
        t.template_db = get_db(data["template_db"]) if data["template_db"] else None
        # Entry templates carry that database's properties.
        t.entry_of = t.template_db
        fields += ["template_db", "entry_of"]
    if fields:
        t.save(update_fields=fields)


@api_view(["PATCH", "DELETE"])
def template_detail(request, tpl_id):
    t = get_doc(tpl_id)
    if not t.is_template:
        return bad("Not a template.")
    if request.method == "DELETE":
        with transaction.atomic():
            search.remove_document(t.id)
            t.delete()
        return Response(status=204)
    with transaction.atomic():
        apply_template_binding(t, request.data)
    return Response(template_json(t))


@api_view(["POST"])
def template_duplicate(request, tpl_id):
    t = get_doc(tpl_id)
    with transaction.atomic():
        copy = copy_document(t, None, title=(t.title or "Untitled") + " (copy)", as_template=True)
    return Response(template_json(copy), status=201)


# ------------------------------------------------------------------ graph


@api_view(["GET"])
def graph(request):
    docs = list(
        Document.objects.filter(trashed_at__isnull=True, is_template=False).values(
            "id", "title", "icon", "parent_id", "entry_of_id", "is_archived"
        )
    )
    alive = {d["id"] for d in docs}
    db_pages = dict(Database.objects.values_list("id", "page_id"))
    nodes = [
        {
            "id": str(d["id"]), "kind": "doc", "title": d["title"], "icon": d["icon"],
            "db": str(d["id"]) in {str(p) for p in db_pages.values()},
            "entry": bool(d["entry_of_id"]), "archived": d["is_archived"],
        }
        for d in docs
    ]
    edges = []
    for d in docs:
        if d["parent_id"] in alive:
            edges.append({"s": str(d["parent_id"]), "t": str(d["id"]), "kind": "child"})
        page = db_pages.get(d["entry_of_id"])
        if page in alive:
            edges.append({"s": str(page), "t": str(d["id"]), "kind": "child"})

    tags = list(Tag.objects.all())
    used_tags = set()
    for doc_id, tag_id in Document.tags.through.objects.filter(document_id__in=alive).values_list(
        "document_id", "tag_id"
    ):
        edges.append({"s": str(doc_id), "t": "tag:" + str(tag_id), "kind": "tag"})
        used_tags.add(tag_id)

    blocks_wanted = set()
    seen = set()
    for src, kind, target, block_id in Link.objects.filter(source_document_id__in=alive).values_list(
        "source_document_id", "target_kind", "target_id", "source_block_id"
    ):
        if kind == "doc":
            key = (str(src), target, "ref")
            if uuid.UUID(target) in alive and target != str(src) and key not in seen:
                seen.add(key)
                edges.append({"s": str(src), "t": target, "kind": "ref"})
        elif kind == "tag":
            key = (str(src), "tag:" + target, "tag")
            if key not in seen:
                seen.add(key)
                edges.append({"s": str(src), "t": "tag:" + target, "kind": "tag"})
                used_tags.add(uuid.UUID(target))
        elif kind == "block":
            blocks_wanted.add(target)
            edges.append({"s": str(src), "t": "block:" + target, "kind": "ref"})

    from .text import one_line
    for b in Block.objects.filter(id__in=blocks_wanted, document_id__in=alive).values(
        "id", "html", "document_id", "type"
    ):
        label = one_line(b["html"], 60) or ("Synced block" if b["type"] == "synced" else b["type"].capitalize())
        nodes.append({"id": "block:" + str(b["id"]), "kind": "block", "title": label,
                      "doc": str(b["document_id"])})
        edges.append({"s": str(b["document_id"]), "t": "block:" + str(b["id"]), "kind": "child"})
    block_nodes = {n["id"] for n in nodes if n["kind"] == "block"}
    edges = [e for e in edges if not e["t"].startswith("block:") or e["t"] in block_nodes]

    for t in tags:
        if t.id in used_tags:
            nodes.append({"id": "tag:" + str(t.id), "kind": "tag", "title": t.name, "color": t.color})

    for doc_id, value in PropertyValue.objects.filter(
        definition__type="relation", document_id__in=alive
    ).values_list("document_id", "value"):
        for target in value or []:
            try:
                if uuid.UUID(target) in alive:
                    a, b = sorted([str(doc_id), target])
                    key = (a, b, "relation")
                    if key not in seen:
                        seen.add(key)
                        edges.append({"s": str(doc_id), "t": target, "kind": "relation"})
            except ValueError:
                continue
    return Response({"nodes": nodes, "edges": edges})
