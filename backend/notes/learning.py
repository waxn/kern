"""Flashcards: turning notes into cards, review queues, statistics."""
import datetime as dt
import re
from collections import Counter

from django.db.models import Q
from django.utils import timezone

from . import fsrs, search
from .models import Block, Card, CardNote, Document, ReviewLog, Setting
from .text import to_text

DEFAULTS = {"new_per_day": 20, "reviews_per_day": 200, "retention": 0.9, "show_intervals": True}
TEXT_TYPES = {"paragraph", "h1", "h2", "h3", "bullet", "numbered", "todo", "toggle", "quote", "callout"}

CLOZE_RE = re.compile(r"\{\{(?:c(\d+)::)?(.+?)(?:::(.+?))?\}\}", re.S)
_TAG_SPLIT = re.compile(r"(<[^>]*>)")


def settings() -> dict:
    s = Setting.objects.filter(key="flashcards").first()
    return {**DEFAULTS, **(s.value if s and isinstance(s.value, dict) else {})}


# ---------------------------------------------------------------- parsing


def _split_outside_tags(html: str, sep: str):
    """Split on the first `sep` that is not inside an HTML tag."""
    pos = 0
    for part in _TAG_SPLIT.split(html):
        if not part.startswith("<"):
            i = part.find(sep)
            if i >= 0:
                return html[: pos + i], html[pos + i + len(sep):]
        pos += len(part)
    return None


def _trim(html: str) -> str:
    return re.sub(r"^(\s|&nbsp;|<br>)+|(\s|&nbsp;|<br>)+$", "", html or "")


def cloze_ordinals(text: str) -> list[int]:
    out, implicit = [], 0
    for m in CLOZE_RE.finditer(text or ""):
        if m.group(1):
            out.append(int(m.group(1)) - 1)
        else:
            out.append(implicit)
            implicit += 1
    return sorted(set(out))


def parse_block(block: Block, children: list[Block]) -> dict | None:
    """Card syntax in a block: `{{cloze}}`, `Question :: Answer`, `Term ;; Definition`.

    With nothing after `::` or `;;`, the block's children form the answer.
    """
    if block.type not in TEXT_TYPES:
        return None
    html = block.html or ""
    if CLOZE_RE.search(html):
        return {"kind": "cloze", "front": html, "back": ""}
    for sep, kind in (("::", "basic"), (";;", "concept")):
        parts = _split_outside_tags(html, sep)
        if parts is None:
            continue
        front, back = _trim(parts[0]), _trim(parts[1])
        if not to_text(front).strip():
            return None
        if not to_text(back).strip():
            back = "<br>".join(c.html for c in children if c.html)
        if not to_text(back).strip():
            return None
        return {"kind": kind, "front": front, "back": back}
    return None


def wanted_ordinals(note: CardNote) -> list[int]:
    if note.kind == "cloze":
        return cloze_ordinals(note.front)
    if note.kind == "concept":
        return [0, 1]
    if note.kind == "occlusion":
        return sorted({int(r.get("n", i)) for i, r in enumerate(note.regions or [])})
    return [0]


def ensure_cards(note: CardNote) -> None:
    want = set(wanted_ordinals(note))
    have = set(note.cards.values_list("ordinal", flat=True))
    Card.objects.bulk_create(Card(note=note, ordinal=o) for o in sorted(want - have))
    note.cards.filter(ordinal__in=have - want).delete()
    index_note(note)


def index_note(note: CardNote) -> None:
    if not note.active:
        search.remove("card", [note.id])
        return
    body = "\n".join(
        t for t in (to_text(CLOZE_RE.sub(lambda m: m.group(2), note.front)), to_text(note.back),
                    " ".join(r.get("label", "") for r in note.regions or [])) if t.strip()
    )
    search._put("card", note.id, note.document_id, "", body)


def sync_blocks(doc: Document, block_ids) -> None:
    """Keep auto-generated notes in step with the card syntax of these blocks."""
    ids = set(block_ids)
    # A change to a child can change its parent's answer.
    ids |= set(Block.objects.filter(id__in=ids, parent__isnull=False).values_list("parent_id", flat=True))
    blocks = list(Block.objects.filter(id__in=ids, document=doc))
    kids: dict = {}
    for c in Block.objects.filter(parent_id__in=[b.id for b in blocks]).order_by("position"):
        kids.setdefault(c.parent_id, []).append(c)
    existing = {n.block_ref: n for n in CardNote.objects.filter(auto=True, block_ref__in=[str(b.id) for b in blocks])}
    for b in blocks:
        if doc.is_template:
            break
        parsed = parse_block(b, kids.get(b.id, []))
        note = existing.get(str(b.id))
        if parsed:
            if not note:
                note = CardNote(auto=True, block_ref=str(b.id))
            note.kind, note.front, note.back = parsed["kind"], parsed["front"], parsed["back"]
            note.document, note.active = doc, True
            note.save()
            ensure_cards(note)
        elif note and note.active:
            note.active = False
            note.save(update_fields=["active", "updated_at"])
            index_note(note)


def deactivate_blocks(block_ids) -> None:
    notes = CardNote.objects.filter(auto=True, block_ref__in=[str(i) for i in block_ids], active=True)
    for n in notes:
        n.active = False
        n.save(update_fields=["active", "updated_at"])
        index_note(n)


# --------------------------------------------------------------- rendering


def render_cloze(text: str, ordinal: int) -> tuple[str, str]:
    implicit = 0

    def repl(show_answer: bool):
        def inner(m):
            nonlocal implicit
            if m.group(1):
                n = int(m.group(1)) - 1
            else:
                n = implicit
                implicit += 1
            if n != ordinal:
                return m.group(2)
            if show_answer:
                return f'<span class="cloze shown">{m.group(2)}</span>'
            hint = m.group(3)
            return f'<span class="cloze">[{hint or "…"}]</span>'
        return inner

    front = CLOZE_RE.sub(repl(False), text)
    implicit = 0
    back = CLOZE_RE.sub(repl(True), text)
    return front, back


def card_json(card: Card, now=None, retention=0.9) -> dict:
    n = card.note
    data = {
        "id": str(card.id), "note": str(n.id), "kind": n.kind, "ordinal": card.ordinal,
        "state": card.state, "due": card.due, "reps": card.reps, "lapses": card.lapses,
        "stability": round(card.stability, 2), "difficulty": round(card.difficulty, 2),
        "suspended": card.suspended, "last_review": card.last_review,
        "deck": str(n.deck_id) if n.deck_id else None,
        "document": str(n.document_id) if n.document_id else None,
        "doc_title": n.document.title if n.document_id else None,
        "block": n.block_ref or None, "auto": n.auto,
    }
    if n.kind == "cloze":
        data["front"], data["back"] = render_cloze(n.front, card.ordinal)
    elif n.kind == "concept" and card.ordinal == 1:
        data["front"], data["back"] = n.back, n.front
    elif n.kind == "occlusion":
        data["front"], data["back"] = n.front, n.back
        data["image"], data["regions"] = n.image, n.regions
    else:
        data["front"], data["back"] = n.front, n.back
    if now is not None:
        data["intervals"] = fsrs.preview(state_of(card), now, retention, str(card.id))
    return data


def note_json(n: CardNote) -> dict:
    return {
        "id": str(n.id), "kind": n.kind, "front": n.front, "back": n.back, "image": n.image,
        "regions": n.regions, "deck": str(n.deck_id) if n.deck_id else None,
        "document": str(n.document_id) if n.document_id else None,
        "doc_title": n.document.title if n.document_id else None,
        "block": n.block_ref or None, "auto": n.auto, "active": n.active,
        "created_at": n.created_at, "updated_at": n.updated_at,
    }


def state_of(card: Card) -> fsrs.State:
    return fsrs.State(
        state=card.state, stability=card.stability, difficulty=card.difficulty, due=card.due,
        last_review=card.last_review, reps=card.reps, lapses=card.lapses, step=card.step,
    )


def snapshot(card: Card) -> dict:
    return {
        "state": card.state, "stability": card.stability, "difficulty": card.difficulty,
        "due": card.due.isoformat() if card.due else None,
        "last_review": card.last_review.isoformat() if card.last_review else None,
        "reps": card.reps, "lapses": card.lapses, "step": card.step,
    }


def restore(card: Card, snap: dict) -> None:
    parse = lambda v: dt.datetime.fromisoformat(v) if v else None
    card.state, card.stability, card.difficulty = snap["state"], snap["stability"], snap["difficulty"]
    card.due, card.last_review = parse(snap["due"]), parse(snap["last_review"])
    card.reps, card.lapses, card.step = snap["reps"], snap["lapses"], snap.get("step", 0)
    card.save()


def apply_review(card: Card, rating: int, duration_ms: int = 0) -> Card:
    now = timezone.now()
    before = snapshot(card)
    st, scheduled = fsrs.review(state_of(card), rating, now, settings()["retention"], str(card.id))
    elapsed = (now - card.last_review).total_seconds() / 86400 if card.last_review else 0
    ReviewLog.objects.create(
        card=card, rating=rating, state=card.state, reviewed_at=now, elapsed_days=elapsed,
        scheduled_days=scheduled, duration_ms=max(0, min(duration_ms, 3_600_000)), before=before,
    )
    card.state, card.stability, card.difficulty = st.state, st.stability, st.difficulty
    card.due, card.last_review, card.reps, card.lapses, card.step = st.due, st.last_review, st.reps, st.lapses, st.step
    card.save()
    return card


# ----------------------------------------------------------------- queues


def day_bounds(tzo_minutes: int):
    """Start and end of the viewer's local day, in UTC. tzo = Date.getTimezoneOffset()."""
    offset = dt.timedelta(minutes=-tzo_minutes)
    local_now = timezone.now() + offset
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_local - offset
    return start, start + dt.timedelta(days=1)


def live_cards():
    return Card.objects.filter(suspended=False, note__active=True).filter(
        Q(note__document__isnull=True) | Q(note__document__trashed_at__isnull=True, note__document__is_template=False)
    )


def scoped(qs, deck=None, doc=None, tag=None, notes=None):
    from .views import subtree_ids

    if deck == "none":
        qs = qs.filter(note__deck__isnull=True)
    elif deck:
        qs = qs.filter(note__deck_id=deck)
    if doc:
        qs = qs.filter(note__document_id__in=subtree_ids(doc))
    if tag:
        qs = qs.filter(note__document__tags__id=tag)
    if notes:
        qs = qs.filter(note_id__in=notes)
    return qs


def budget(start):
    cfg = settings()
    today = ReviewLog.objects.filter(reviewed_at__gte=start)
    new_done = today.filter(state="new").values("card").distinct().count()
    rev_done = today.filter(state="review").count()
    return max(0, cfg["new_per_day"] - new_done), max(0, cfg["reviews_per_day"] - rev_done)


def queue(tzo: int, **scope) -> dict:
    now = timezone.now()
    start, end = day_bounds(tzo)
    new_left, rev_left = budget(start)
    base = scoped(live_cards(), **scope).select_related("note", "note__document")
    learning = list(base.filter(state__in=["learning", "relearning"], due__lte=now).order_by("due"))
    # Bury siblings: other cards of a note seen today wait until tomorrow.
    seen = set(ReviewLog.objects.filter(reviewed_at__gte=start).values_list("card__note_id", flat=True))
    reviews = list(base.filter(state="review", due__lt=end).exclude(note_id__in=seen).order_by("due")[:rev_left])
    news, picked = [], set()
    for c in base.filter(state="new").exclude(note_id__in=seen).order_by("note__created_at", "ordinal"):
        if len(news) >= new_left:
            break
        if c.note_id in picked:
            continue  # one new card per note per day
        picked.add(c.note_id)
        news.append(c)
    later = base.filter(state__in=["learning", "relearning"], due__gt=now, due__lt=end).order_by("due").first()
    order = learning + reviews + news
    retention = settings()["retention"]
    return {
        "card": card_json(order[0], now, retention) if order else None,
        "counts": {"learning": len(learning), "review": len(reviews), "new": len(news)},
        "next_learning": later.due if later else None,
    }


def stats(tzo: int) -> dict:
    now = timezone.now()
    start, end = day_bounds(tzo)
    new_left, rev_left = budget(start)
    cards = live_cards()
    by_state = Counter(cards.values_list("state", flat=True))
    logs_today = ReviewLog.objects.filter(reviewed_at__gte=start)
    month = ReviewLog.objects.filter(reviewed_at__gte=start - dt.timedelta(days=30), state="review")
    m_total = month.count()

    offset = dt.timedelta(minutes=-tzo)
    forecast = Counter()
    for due in cards.filter(state="review", due__lt=start + dt.timedelta(days=30)).values_list("due", flat=True):
        day = max(0, ((due + offset).date() - (start + offset).date()).days)
        forecast[day] += 1
    history = Counter()
    for at in ReviewLog.objects.filter(reviewed_at__gte=start - dt.timedelta(days=182)).values_list("reviewed_at", flat=True):
        history[(at + offset).date().isoformat()] += 1

    due_now = cards.filter(Q(state="review", due__lt=end) | Q(state__in=["learning", "relearning"], due__lt=end)).count()
    return {
        "due_today": min(due_now, rev_left + by_state.get("learning", 0) + by_state.get("relearning", 0)),
        "due_total": due_now,
        "new_available": min(by_state.get("new", 0), new_left),
        "reviewed_today": logs_today.count(),
        "time_today_ms": sum(logs_today.values_list("duration_ms", flat=True)),
        "accuracy_today": _accuracy(logs_today.filter(state="review")),
        "accuracy_30d": round(100 * month.filter(rating__gt=1).count() / m_total) if m_total else None,
        "counts": {s: by_state.get(s, 0) for s in Card.STATES},
        "suspended": Card.objects.filter(suspended=True, note__active=True).count(),
        "forecast": [forecast.get(i, 0) for i in range(30)],
        "history": history,
        "settings": settings(),
    }


def _accuracy(qs):
    total = qs.count()
    return round(100 * qs.filter(rating__gt=1).count() / total) if total else None
