"""Document version history: periodic snapshots, pruning and restore."""
import datetime as dt

from django.utils import timezone

from .models import Block, DocVersion, Document

GAP = dt.timedelta(minutes=10)  # one automatic snapshot per editing burst


def block_rows(doc: Document) -> list[dict]:
    return [
        {"id": str(b.id), "parent": str(b.parent_id) if b.parent_id else None, "position": b.position,
         "type": b.type, "html": b.html, "props": b.props or {}, "collapsed": b.collapsed}
        for b in doc.blocks.order_by("position", "created_at")
    ]


def snapshot(doc: Document, reason: str = "auto") -> DocVersion:
    rows = block_rows(doc)
    v = DocVersion.objects.create(
        document=doc, created_at=timezone.now(), title=doc.title, icon=doc.icon,
        blocks=rows, reason=reason, block_count=len(rows),
    )
    prune(doc)
    return v


def maybe_snapshot(doc: Document) -> None:
    """Called before a change is applied: keep the state an editing burst started from."""
    if doc.is_template:
        return
    last = doc.versions.order_by("-created_at").values_list("created_at", flat=True).first()
    if last and timezone.now() - last < GAP:
        return
    if not last and not doc.blocks.exists():
        return
    if last:
        latest = doc.versions.order_by("-created_at").first()
        if latest.blocks == block_rows(doc) and latest.title == doc.title:
            return
    snapshot(doc)


def prune(doc: Document) -> None:
    """Keep everything from the last 2 days, then one per day (90 days), then one per week."""
    now = timezone.now()
    keep_day, keep_week, drop = set(), set(), []
    for v in doc.versions.filter(reason="auto", created_at__lt=now - dt.timedelta(days=2)).order_by("-created_at"):
        age = now - v.created_at
        if age < dt.timedelta(days=90):
            key = v.created_at.date()
            bucket = keep_day
        else:
            key = v.created_at.isocalendar()[:2]
            bucket = keep_week
        if key in bucket:
            drop.append(v.id)
        else:
            bucket.add(key)
    if drop:
        DocVersion.objects.filter(id__in=drop).delete()


def restore(doc: Document, v: DocVersion) -> None:
    from . import learning, tasks
    from .views import reindex_blocks
    from . import search

    snapshot(doc, "restore")
    old_ids = list(doc.blocks.values_list("id", flat=True))
    search.remove("block", old_ids)
    learning.deactivate_blocks(old_ids)
    doc.blocks.all().delete()
    rows = v.blocks
    ids = {r["id"] for r in rows}
    new = [
        Block(id=r["id"], document=doc, parent_id=r["parent"] if r["parent"] in ids else None,
              position=r["position"], type=r["type"], html=r["html"], props=r["props"],
              collapsed=r["collapsed"])
        for r in rows
    ]
    # Insert parents before children so foreign keys hold.
    by_id = {b.id: b for b in new}
    ordered, seen = [], set()

    def add(b):
        if str(b.id) in seen:
            return
        if b.parent_id and str(b.parent_id) in by_id:
            add(by_id[str(b.parent_id)])
        seen.add(str(b.id))
        ordered.append(b)

    for b in new:
        add(b)
    Block.objects.bulk_create(ordered)
    saved = list(doc.blocks.all())
    reindex_blocks(doc, saved)
    learning.sync_blocks(doc, [b.id for b in saved])
    tasks.sync_blocks(doc, saved)
    doc.title, doc.icon = v.title, v.icon
    doc.updated_at = timezone.now()
    doc.save(update_fields=["title", "icon", "updated_at"])
    search.index_document(doc)
