"""Flashcard and task endpoints."""
import datetime as dt
import uuid

from django.db import transaction
from kern import tenancy
from django.db.models import Max, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import learning, search, tasks
from .models import Block, Card, CardNote, Deck, Document, ReviewLog, Tag, Task
from .porting import sanitize_card
from .text import one_line, sanitize
from .views import as_uuid, bad, get_doc


def _tzo(request) -> int:
    try:
        return max(-900, min(900, int(request.query_params.get("tzo", 0))))
    except ValueError:
        return 0


def _scope(request) -> dict:
    q = request.query_params
    return {"deck": q.get("deck") or None, "doc": as_uuid(q["doc"]) if q.get("doc") else None,
            "tag": as_uuid(q["tag"]) if q.get("tag") else None}


def _get(model, pk):
    try:
        return model.objects.get(id=as_uuid(pk))
    except model.DoesNotExist:
        raise Http404


# ------------------------------------------------------------------ decks


def deck_json(d: Deck, counts=None) -> dict:
    return {"id": str(d.id), "name": d.name, **(counts or {})}


@api_view(["GET", "POST"])
def decks(request):
    if request.method == "POST":
        name = str(request.data.get("name", "")).strip()[:120]
        if not name:
            return bad("Deck name is required.")
        return Response(deck_json(Deck.objects.create(name=name)), status=201)
    tzo = _tzo(request)
    start, end = learning.day_bounds(tzo)
    now = timezone.now()
    out = []
    for d in [None, *Deck.objects.all()]:
        qs = learning.scoped(learning.live_cards(), deck=str(d.id) if d else "none")
        counts = {
            "total": qs.count(), "new": qs.filter(state="new").count(),
            "due": qs.filter(Q(state="review", due__lt=end) | Q(state__in=["learning", "relearning"], due__lte=now)).count(),
        }
        if d is None:
            if counts["total"]:
                out.append({"id": "none", "name": "Default", **counts})
        else:
            out.append(deck_json(d, counts))
    return Response(out)


@api_view(["PATCH", "DELETE"])
def deck_detail(request, deck_id):
    d = _get(Deck, deck_id)
    if request.method == "DELETE":
        d.delete()  # its notes fall back to the default deck
        return Response(status=204)
    name = str(request.data.get("name", "")).strip()[:120]
    if name:
        d.name = name
        d.save()
    return Response(deck_json(d))


# ------------------------------------------------------------------ notes


def _clean_regions(regions):
    out, used = [], set()
    for r in regions if isinstance(regions, list) else []:
        try:
            n = int(r.get("n", len(out)))
            if n in used:
                n = max(used) + 1
            used.add(n)
            out.append({
                "id": str(r.get("id") or uuid.uuid4()), "n": n,
                "x": max(0.0, min(1.0, float(r["x"]))), "y": max(0.0, min(1.0, float(r["y"]))),
                "w": max(0.0, min(1.0, float(r["w"]))), "h": max(0.0, min(1.0, float(r["h"]))),
                "label": str(r.get("label", ""))[:200],
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _apply_note(n: CardNote, data: dict, creating: bool) -> None:
    if "deck" in data:
        n.deck = Deck.objects.filter(id=as_uuid(data["deck"])).first() if data["deck"] and data["deck"] != "none" else None
    if n.auto and not creating:
        return  # content comes from the source block
    if "kind" in data:
        if data["kind"] not in CardNote.KINDS:
            raise ValueError("Unknown card type.")
        n.kind = data["kind"]
    for field in ("front", "back"):
        if field in data:
            setattr(n, field, sanitize_card(str(data[field] or ""))[:20000])
    if "image" in data:
        n.image = str(data["image"] or "")[:500]
    if "regions" in data:
        n.regions = _clean_regions(data["regions"])
    if creating:
        if data.get("document"):
            n.document = get_doc(data["document"], include_trashed=False)
        if data.get("block"):
            b = Block.objects.filter(id=as_uuid(data["block"])).first()
            if b:
                n.block_ref = str(b.id)
                n.document = n.document or b.document


def _validate(n: CardNote):
    from .text import to_text
    if n.kind == "occlusion":
        if not n.image or not n.regions:
            return "Add an image and at least one hidden region."
    elif n.kind == "cloze":
        if not learning.cloze_ordinals(n.front):
            return "Mark at least one gap with {{double braces}}."
    elif not to_text(n.front).strip() or not to_text(n.back).strip():
        return "Both sides of the card need content."
    return None


@api_view(["POST"])
def notes(request):
    n = CardNote()
    try:
        _apply_note(n, request.data, creating=True)
    except ValueError as e:
        return bad(str(e))
    err = _validate(n)
    if err:
        return bad(err)
    with tenancy.atomic():
        n.save()
        learning.ensure_cards(n)
    return Response(learning.note_json(n), status=201)


@api_view(["GET", "PATCH", "DELETE"])
def note_detail(request, note_id):
    n = _get(CardNote, note_id)
    if request.method == "GET":
        data = learning.note_json(n)
        data["cards"] = [learning.card_json(c) for c in n.cards.order_by("ordinal")]
        return Response(data)
    if request.method == "DELETE":
        with tenancy.atomic():
            search.remove("card", [n.id])
            n.delete()
        return Response(status=204)
    try:
        _apply_note(n, request.data, creating=False)
    except ValueError as e:
        return bad(str(e))
    err = _validate(n)
    if err:
        return bad(err)
    with tenancy.atomic():
        n.save()
        learning.ensure_cards(n)
    return Response(learning.note_json(n))


# ------------------------------------------------------------------ cards


@api_view(["GET"])
def cards(request):
    q = request.query_params
    qs = Card.objects.filter(note__active=True).filter(
        Q(note__document__isnull=True) | Q(note__document__trashed_at__isnull=True)
    ).select_related("note", "note__document")
    qs = learning.scoped(qs, **_scope(request))
    state = q.get("state")
    if state == "suspended":
        qs = qs.filter(suspended=True)
    elif state == "due":
        qs = qs.filter(suspended=False, due__lte=timezone.now())
    elif state in Card.STATES:
        qs = qs.filter(state=state, suspended=False)
    if q.get("q"):
        rows, _ = search.search(q["q"], "card", 500, 0)
        qs = qs.filter(note_id__in=[r[1] for r in rows])
    if q.get("note"):
        qs = qs.filter(note_id=as_uuid(q["note"]))
    if q.get("block"):
        qs = qs.filter(note__block_ref=str(as_uuid(q["block"])))
    total = qs.count()
    limit = min(int(q.get("limit", 100)), 500)
    offset = int(q.get("offset", 0))
    page = qs.order_by("-note__created_at", "ordinal")[offset: offset + limit]
    return Response({"total": total, "cards": [learning.card_json(c) for c in page]})


@api_view(["POST"])
def cards_bulk(request):
    ids = [as_uuid(i) for i in request.data.get("ids") or []]
    action = request.data.get("action")
    qs = Card.objects.filter(id__in=ids)
    with tenancy.atomic():
        if action == "suspend":
            qs.update(suspended=True)
        elif action == "unsuspend":
            qs.update(suspended=False)
        elif action == "reset":
            qs.update(state="new", due=None, stability=0, difficulty=0, reps=0, lapses=0, step=0, last_review=None)
        elif action == "deck":
            deck = request.data.get("deck")
            d = Deck.objects.filter(id=as_uuid(deck)).first() if deck and deck != "none" else None
            CardNote.objects.filter(cards__id__in=ids).update(deck=d)
        elif action == "delete":
            note_ids = set(qs.values_list("note_id", flat=True))
            qs.delete()
            # A note without cards left is gone too (auto notes would regenerate them).
            for n in CardNote.objects.filter(id__in=note_ids):
                if n.auto:
                    n.active = False
                    n.save(update_fields=["active"])
                    learning.index_note(n)
                elif not n.cards.exists():
                    search.remove("card", [n.id])
                    n.delete()
        else:
            return bad("Unknown action.")
    return Response({"ok": True})


@api_view(["GET"])
def card_queue(request):
    return Response(learning.queue(_tzo(request), **_scope(request)))


@api_view(["GET"])
def card_stats(request):
    return Response(learning.stats(_tzo(request)))


@api_view(["POST"])
def card_review(request, card_id):
    card = _get(Card, card_id)
    try:
        rating = int(request.data.get("rating"))
    except (TypeError, ValueError):
        return bad("Rating must be 1–4.")
    if rating not in (1, 2, 3, 4):
        return bad("Rating must be 1–4.")
    with tenancy.atomic():
        card = learning.apply_review(card, rating, int(request.data.get("duration_ms") or 0))
    return Response(learning.card_json(card))


@api_view(["POST"])
def card_undo(request):
    log = ReviewLog.objects.order_by("-reviewed_at", "-id").first()
    if not log or not log.before:
        return bad("Nothing to undo.")
    if timezone.now() - log.reviewed_at > dt.timedelta(hours=12):
        return bad("The last review is too old to undo.")
    with tenancy.atomic():
        card = log.card
        learning.restore(card, log.before)
        log.delete()
    return Response(learning.card_json(card))


# ------------------------------------------------------------------ tasks


def _date(v):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError("Dates must look like 2026-11-10.")


def _apply_task(t: Task, data: dict) -> list:
    tag_ids = None
    if "title" in data:
        t.title = str(data["title"] or "")[:500]
    if "description" in data:
        t.description = str(data["description"] or "")[:20000]
    if "priority" in data:
        t.priority = max(0, min(3, int(data["priority"] or 0)))
    if "due" in data:
        t.due = _date(data["due"])
    if "start" in data:
        t.start = _date(data["start"])
    if "recurrence" in data:
        t.recurrence = tasks.clean_recurrence(data["recurrence"])
    if "project" in data:
        t.project = get_doc(data["project"], include_trashed=False) if data["project"] else None
    if "document" in data:
        t.document = get_doc(data["document"], include_trashed=False) if data["document"] else None
    if "tags" in data:
        tag_ids = [as_uuid(x) for x in data["tags"] or []]
    return tag_ids


@api_view(["GET", "POST"])
def task_list(request):
    if request.method == "POST":
        data = request.data
        t = Task()
        try:
            tag_ids = _apply_task(t, data)
        except (ValueError, TypeError) as e:
            return bad(str(e))
        with tenancy.atomic():
            if data.get("block"):
                b = Block.objects.filter(id=as_uuid(data["block"])).select_related("document").first()
                if not b:
                    return bad("Save the page first, then try again.")
                existing = Task.objects.filter(block=b).first()
                if existing:
                    return Response(tasks.task_json(existing))
                t.block, t.document = b, b.document
                t.title = t.title or one_line(b.html, 500)
                if b.type != "todo":
                    b.type = "todo"
                t.done = bool((b.props or {}).get("checked"))
                b.props = {**(b.props or {}), "task": str(t.id), "checked": t.done}
                b.save()
            top = Task.objects.aggregate(m=Max("position"))["m"] or 0
            t.position = top + 1
            t.save()
            if tag_ids is not None:
                t.tags.set(Tag.objects.filter(id__in=tag_ids))
            tasks.index_task(t)
        return Response(tasks.task_json(t), status=201)

    q = request.query_params
    try:
        today = _date(q.get("today")) or timezone.localdate()
    except ValueError as e:
        return bad(str(e))
    view = q.get("view", "all")
    qs = Task.objects.all().prefetch_related("tags")
    qs = qs.exclude(document__trashed_at__isnull=False)
    if view == "inbox":
        qs = qs.filter(done=False, due__isnull=True, project__isnull=True, document__isnull=True)
    elif view == "today":
        qs = qs.filter(done=False, due__lte=today)
    elif view == "upcoming":
        qs = qs.filter(done=False, due__gt=today)
    elif view == "completed":
        qs = qs.filter(done=True)
    elif view == "open":
        qs = qs.filter(done=False)
    if q.get("project"):
        qs = qs.filter(project_id=as_uuid(q["project"]))
    if q.get("document"):
        qs = qs.filter(document_id=as_uuid(q["document"]))
    if q.get("tag"):
        qs = qs.filter(tags__id=as_uuid(q["tag"]))
    if q.get("priority"):
        qs = qs.filter(priority__gte=int(q["priority"]))
    if q.get("q"):
        rows, _ = search.search(q["q"], "task", 500, 0)
        qs = qs.filter(id__in=[r[1] for r in rows])
    order = {
        "due": ["due", "-priority", "position"], "priority": ["-priority", "due", "position"],
        "created": ["-created_at"], "title": ["title"], "completed": ["-completed_at"],
    }.get(q.get("sort") or ("completed" if view == "completed" else "due"), ["due", "position"])
    # Undated tasks sort after dated ones.
    from django.db.models import F
    qs = qs.order_by(*[F(o.lstrip("-")).desc(nulls_last=True) if o.startswith("-") else F(o).asc(nulls_last=True) for o in order])
    return Response([tasks.task_json(t) for t in qs.distinct()[:1000]])


@api_view(["GET"])
def task_summary(request):
    try:
        today = _date(request.query_params.get("today")) or timezone.localdate()
    except ValueError as e:
        return bad(str(e))
    open_ = Task.objects.filter(done=False).exclude(document__trashed_at__isnull=False)
    week_ago = timezone.now() - dt.timedelta(days=7)
    return Response({
        "inbox": open_.filter(due__isnull=True, project__isnull=True, document__isnull=True).count(),
        "today": open_.filter(due=today).count(),
        "overdue": open_.filter(due__lt=today).count(),
        "upcoming": open_.filter(due__gt=today, due__lte=today + dt.timedelta(days=7)).count(),
        "open": open_.count(),
        "completed_week": Task.objects.filter(done=True, completed_at__gte=week_ago).count(),
    })


@api_view(["GET", "PATCH", "DELETE"])
def task_detail(request, task_id):
    t = _get(Task, task_id)
    if request.method == "GET":
        return Response(tasks.task_json(t))
    if request.method == "DELETE":
        with tenancy.atomic():
            if t.block_id:
                b = t.block
                b.props = {k: v for k, v in (b.props or {}).items() if k != "task"}
                b.save(update_fields=["props"])
            search.remove("task", [t.id])
            t.delete()
        return Response(status=204)
    data = request.data
    with tenancy.atomic():
        try:
            tag_ids = _apply_task(t, data)
        except (ValueError, TypeError) as e:
            return bad(str(e))
        if t.block_id and "title" in data:
            # The checklist block is the source of the title; keep them equal.
            from .text import sanitize as clean
            b = t.block
            b.html = clean(t.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            b.save(update_fields=["html", "updated_at"])
            from .views import reindex_blocks
            reindex_blocks(b.document, [b])
        t.save()
        if tag_ids is not None:
            t.tags.set(Tag.objects.filter(id__in=tag_ids))
        if "done" in data:
            tasks.set_done(t, bool(data["done"]), _date(data.get("today")) or None)
        tasks.index_task(t)
    return Response(tasks.task_json(t))
