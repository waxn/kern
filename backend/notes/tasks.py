"""Tasks: recurrence and keeping tasks, checklist blocks and database entries in step."""
import calendar
import datetime as dt

from django.utils import timezone

from . import search
from .models import Block, Document, PropertyDef, PropertyValue, Task
from .text import one_line

FREQS = {"day", "week", "month", "year"}


def task_json(t: Task) -> dict:
    return {
        "id": str(t.id), "title": t.title, "description": t.description, "done": t.done,
        "completed_at": t.completed_at, "priority": t.priority,
        "due": t.due.isoformat() if t.due else None,
        "start": t.start.isoformat() if t.start else None,
        "recurrence": t.recurrence,
        "document": str(t.document_id) if t.document_id else None,
        "project": str(t.project_id) if t.project_id else None,
        "block": str(t.block_id) if t.block_id else None,
        "tags": [str(x) for x in t.tags.values_list("id", flat=True)],
        "position": t.position, "created_at": t.created_at, "updated_at": t.updated_at,
    }


def clean_recurrence(value):
    if not isinstance(value, dict) or value.get("freq") not in FREQS:
        return None
    try:
        n = max(1, min(365, int(value.get("interval", 1))))
    except (TypeError, ValueError):
        n = 1
    return {"freq": value["freq"], "interval": n}


def shift(d: dt.date, rule: dict) -> dt.date:
    n = rule.get("interval", 1)
    f = rule["freq"]
    if f == "day":
        return d + dt.timedelta(days=n)
    if f == "week":
        return d + dt.timedelta(weeks=n)
    months = n * (12 if f == "year" else 1)
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def advance(t: Task, today: dt.date) -> None:
    """Move a recurring task to its next occurrence after today."""
    rule = t.recurrence
    base = t.due or today
    nxt = shift(base, rule)
    while nxt <= today:  # skip missed occurrences
        nxt = shift(nxt, rule)
    if t.start and t.due:
        t.start = t.start + (nxt - t.due)
    elif t.start:
        t.start = shift(t.start, rule)
    t.due = nxt


def set_done(t: Task, done: bool, today: dt.date | None = None) -> None:
    """Complete or reopen a task, propagating to its block and database entry."""
    today = today or timezone.localdate()
    if done and t.recurrence:
        advance(t, today)
        t.completed_at = timezone.now()
        t.done = False
    else:
        t.done = done
        t.completed_at = timezone.now() if done else None
    t.save()
    if t.block_id:
        b = Block.objects.filter(id=t.block_id).first()
        if b and b.type == "todo" and bool((b.props or {}).get("checked")) != t.done:
            b.props = {**(b.props or {}), "checked": t.done}
            b.save(update_fields=["props", "updated_at"])
    # A task attached to an entry (not one of its checklist items) completes the entry.
    if t.document_id and done and not t.recurrence and not t.block_id:
        mark_entry_done(t.document)
    index_task(t)


def mark_entry_done(doc: Document) -> None:
    """For a database entry, tick its status ("done" group) or first checkbox."""
    if not doc.entry_of_id:
        return
    props = PropertyDef.objects.filter(database_id=doc.entry_of_id).order_by("position")
    status = next((p for p in props if p.type == "status"), None)
    if status:
        done = next((o for o in status.options or [] if o.get("group") == "done"), None)
        if done:
            PropertyValue.objects.update_or_create(document=doc, definition=status, defaults={"value": done["id"]})
            return
    box = next((p for p in props if p.type == "boolean"), None)
    if box:
        PropertyValue.objects.update_or_create(document=doc, definition=box, defaults={"value": True})


def sync_blocks(doc: Document, blocks) -> list[Block]:
    """Checklist blocks linked to tasks: block text and tick drive the task.

    Returns blocks the server changed (a recurring task un-ticks its block)."""
    patched = []
    today = timezone.localdate()
    for b in blocks:
        tid = (b.props or {}).get("task")
        if b.type != "todo" or not tid:
            continue
        t = Task.objects.filter(id=tid).first()
        if not t:
            continue
        changed = False
        title = one_line(b.html, 500)
        if t.block_id != b.id:
            if Task.objects.filter(block_id=b.id).exclude(id=t.id).exists():
                continue  # another task owns this block (e.g. after a duplicate)
            t.block_id, changed = b.id, True
        if t.document_id != doc.id:
            t.document_id, changed = doc.id, True
        if title != t.title:
            t.title, changed = title, True
        checked = bool((b.props or {}).get("checked"))
        if checked != t.done:
            if checked and t.recurrence:
                set_done(t, True, today)
                b.refresh_from_db()
                patched.append(b)
                continue
            t.done = checked
            t.completed_at = timezone.now() if checked else None
            changed = True
        if changed:
            t.save()
            index_task(t)
    return patched


def index_task(t: Task) -> None:
    search._put("task", t.id, t.document_id, t.title, t.description)
