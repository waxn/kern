"""JSON API for the Svelte frontend. Every view here requires a logged-in
session (enforced by accounts.middleware.ApiLoginRequiredMiddleware)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header

from .. import mute as mute_mod
from .. import preferences as prefs_mod
from .. import actions, followups, imgproxy, labels as labels_mod, parsing, private_ai, risk, sanitize, search, sending, snooze, spam, store
from ..identity import my_addresses
from ..models import (
    Attachment, BlockRule, Correspondent, Draft, DraftStatus, Folder, FolderRole, Label, Message,
    MailIdentity, OpStatus, OutboxOp, Thread, ThreadFolder, TrustedImageSender, Upload, WorkerStatus,
)
from .util import ApiError, api, body, int_or_none, iso
from mail.account import cfg as _mail_cfg

PAGE = 50
ROLE_ORDER = {"inbox": 0, "snoozed": 1, "drafts": 2, "sent": 3, "archive": 4, "junk": 5, "trash": 6, "all": 7, "": 8}


# --- serializers -------------------------------------------------------------

def folder_json(f: Folder, unread: int = 0, total: int = 0) -> dict:
    return {"id": f.id, "name": f.name, "displayName": f.display_name, "role": f.role,
            "unread": unread, "total": total, "syncing": not f.initial_sync_done and not f.needs_create,
            "delimiter": f.delimiter}


def label_json(lb: Label) -> dict:
    return {"id": lb.id, "name": lb.name, "color": lb.color}


def followup_json(f) -> dict:
    return {"id": f.id, "status": f.status, "due": iso(f.due_at), "sentAt": iso(f.sent_at),
            "subject": f.subject, "recipients": f.recipients, "threadId": f.thread_id}


def thread_json(t: Thread, folders: dict[int, list[int]] | None = None, snoozes: dict | None = None,
                fups: dict | None = None, muted: set | None = None, pkgs: dict | None = None,
                me: set | None = None) -> dict:
    from ..names import participants_label

    s = (snoozes or {}).get(t.id)
    f = (fups or {}).get(t.id)
    return {
        "id": t.id,
        "who": participants_label(t.participants, my_addresses() if me is None else me),
        "subject": t.subject,
        "snippet": t.snippet,
        "lastDate": iso(t.last_date),
        "count": t.message_count,
        "unread": t.unread_count,
        "starred": t.starred,
        "hasAttachments": t.has_attachments,
        "participants": t.participants,
        "risk": t.risk_level,
        "labels": t.label_ids,
        "folders": (folders or {}).get(t.id, []),
        "snoozeUntil": iso(s.wake_at) if s else None,
        "followup": followup_json(f) if f else None,
        "muted": t.id in (muted or set()),
        "package": (pkgs or {}).get(t.id),
    }


def message_json(m: Message, drafts_by_key: dict[str, int]) -> dict:
    return {
        "id": m.id,
        "threadId": m.thread_id,
        "folder": {"id": m.folder_id, "name": m.folder.display_name, "role": m.folder.role},
        "messageId": m.message_id,
        "from": {"name": m.from_name, "addr": m.from_addr},
        "to": m.to_addrs,
        "cc": m.cc_addrs,
        "bcc": m.bcc_addrs,
        "replyTo": m.reply_to,
        "subject": m.subject,
        "date": iso(m.sort_date),
        "seen": m.seen,
        "flagged": m.flagged,
        "answered": m.answered,
        "isDraft": m.is_draft,
        "draftId": drafts_by_key.get(m.message_key),
        "snippet": m.snippet,
        "hasHtml": m.has_html,
        "size": m.size,
        "labels": [lb.id for lb in m.labels.all()],
        "attachments": [
            {"id": a.id, "filename": a.filename, "contentType": a.content_type, "size": a.size,
             "inline": a.inline, "previewable": _previewable(a.content_type),
             "preview": _preview(a.content_type, a.filename, a.size)}
            for a in m.attachments.all()
        ],
        "risk": {"level": m.risk_level, "score": m.risk_score,
                 "findings": [f for f in m.risk_findings if f.get("rule") != "private-sort"]},
        "privateSort": private_ai.note_for(m),
        "auth": m.auth_results,
        "listUnsubscribe": m.headers.get("list-unsubscribe", ""),
        "unsubscribe": _unsub_json(m),
        "blockedBy": ({"kind": m.routed_by_block.kind, "value": m.routed_by_block.value}
                      if m.routed_by_block_id and m.routed_by_block else None),
        "pending": m.folder_id != m.server_folder_id or m.uid is None,
        "fromMe": m.from_addr in my_addresses(),
        "defects": bool(m.parse_defects),
    }


def _unsub_json(m: Message):
    from .. import unsubscribe

    o = unsubscribe.options(m)
    return {"oneClick": o.one_click, "url": o.https, "mailto": o.mailto} if o else None


INLINE_SAFE = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp"}

# Audio and video the browser plays itself. A media type with nosniff can't run
# script, so these are served inline (with Range, so players can seek). Senders
# often label them application/octet-stream, so the file name is checked too.
MEDIA_EXT = {
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "oga": "audio/ogg",
    "opus": "audio/ogg", "wav": "audio/wav", "flac": "audio/flac", "weba": "audio/webm",
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "ogv": "video/ogg", "mov": "video/quicktime",
}
MEDIA_SAFE = set(MEDIA_EXT.values()) | {"audio/mp3", "audio/x-m4a", "audio/x-wav", "audio/wave", "audio/x-flac"}
TEXT_EXT = {"txt", "text", "log", "csv", "tsv", "json", "xml", "yaml", "yml", "toml", "ini", "md", "markdown", "ics", "vcf"}
TEXT_MAX = 2 * 1024 * 1024
HTML_MAX = 5 * 1024 * 1024


def _previewable(ctype: str) -> bool:
    return ctype.lower() in INLINE_SAFE


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _media_type(ctype: str, filename: str) -> str | None:
    ct = (ctype or "").lower().split(";")[0].strip()
    if ct in MEDIA_SAFE:
        return ct
    if ct in ("", "application/octet-stream") or ct.startswith(("audio/", "video/")):
        return MEDIA_EXT.get(_ext(filename))
    return None


def _preview(ctype: str, filename: str, size: int) -> str | None:
    """How the web app can show this attachment, or None (download only). Only
    images and media are ever rendered by the browser from our origin; PDFs
    and Word files are drawn by pdf.js / mammoth from bytes, HTML goes through
    the email sanitizer, text is shown as text."""
    ct, ext = (ctype or "").lower(), _ext(filename)
    if ct in INLINE_SAFE:
        return "image"
    media = _media_type(ct, filename)
    if media:
        return media.split("/")[0]
    if ct == "application/pdf" or ext == "pdf":
        return "pdf"
    if ct in ("text/html", "application/xhtml+xml") or ext in ("html", "htm", "xhtml"):
        return "html" if size <= HTML_MAX else None
    if ext == "docx" or ct == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if ext in TEXT_EXT or ct in ("text/plain", "text/csv", "application/json", "text/calendar", "text/vcard"):
        return "text" if size <= TEXT_MAX else None
    return None


def _ranged(request, data: bytes, ctype: str) -> HttpResponse:
    size = len(data)
    m = _RANGE_RE.match(request.headers.get("Range", "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
        else:
            start, end = max(0, size - int(m.group(2))), size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        resp = HttpResponse(data[start:end + 1], status=206, content_type=ctype)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    else:
        resp = HttpResponse(data, content_type=ctype)
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


# --- info / folders / labels -------------------------------------------------

def _op_description(op: OutboxOp) -> str:
    p = op.payload or {}
    n = len(p.get("message_ids", []) or p.get("locations", []))
    plural = lambda k: f"{k} message{'' if k == 1 else 's'}"  # noqa: E731
    first = Message.objects.filter(pk__in=p.get("message_ids", [])[:1]).values_list("subject", flat=True).first()
    about = f" (“{first[:60]}”)" if first else ""
    if op.kind == "flags":
        what = ", ".join([f"+{f}" for f in p.get("add", [])] + [f"−{f}" for f in p.get("remove", [])])
        return f"Update flags {what} on {plural(n)}{about}"
    if op.kind == "move":
        dest = Folder.objects.filter(pk=p.get("dest")).values_list("name", flat=True).first() or "?"
        return f"Move {plural(n)} to {dest}{about}"
    if op.kind == "expunge":
        return f"Permanently delete {plural(n)}"
    if op.kind in ("send", "save_draft"):
        subj = Draft.objects.filter(pk=p.get("draft")).values_list("subject", flat=True).first() or ""
        return f"{'Send' if op.kind == 'send' else 'Save draft'} “{subj[:60] or '(no subject)'}”"
    if op.kind == "append":
        return "Save a copy of sent mail"
    if op.kind == "create_folder":
        name = Folder.objects.filter(pk=p.get("folder")).values_list("name", flat=True).first() or "?"
        return f"Create folder {name}"
    if op.kind == "delete_server_draft":
        return "Remove an old draft copy"
    return op.kind


@api()
def ops_failed(request):
    since = timezone.now() - timedelta(days=7)
    ops = OutboxOp.objects.filter(status=OpStatus.FAILED, finished__gte=since).order_by("-finished")[:50]
    return [{"id": o.id, "kind": o.kind, "description": _op_description(o), "error": o.last_error[:300],
             "failedAt": iso(o.finished)} for o in ops]


@api(("POST",))
def op_action(request, pk: int):
    op = OutboxOp.objects.get(pk=pk, status=OpStatus.FAILED)
    action = body(request).get("action")
    if action == "dismiss":
        op.status = OpStatus.CANCELLED
        op.save(update_fields=["status"])
        return {"ok": True}
    if action != "retry":
        raise ApiError("Unknown action.")
    if op.kind == "move":
        # The failed move was undone locally; show the messages where they're headed again.
        Message.objects.filter(pk__in=op.payload.get("message_ids", [])).update(folder_id=op.payload.get("dest"))
        for tid in set(Message.objects.filter(pk__in=op.payload.get("message_ids", [])).values_list("thread_id", flat=True)):
            from ..threads import refresh_thread

            refresh_thread(tid)
    if op.kind == "send":
        Draft.objects.filter(pk=op.payload.get("draft")).update(status=DraftStatus.QUEUED, error="")
    op.status, op.attempts, op.not_before, op.last_error, op.finished = OpStatus.PENDING, 0, None, "", None
    op.save(update_fields=["status", "attempts", "not_before", "last_error", "finished"])
    return {"ok": True}


@api(("GET", "PATCH"))
def preferences_view(request):
    from .. import preferences

    if request.method == "PATCH":
        try:
            return preferences.update(body(request))
        except (TypeError, ValueError) as exc:
            raise ApiError(str(exc)) from exc
    return preferences.get()


@api()
def info(request):
    ws = WorkerStatus.objects.filter(pk=1).first()
    stale = not ws or not ws.heartbeat or (timezone.now() - ws.heartbeat).total_seconds() > 120
    return {
        "address": _mail_cfg()["USERNAME"],
        "fromName": prefs_mod.from_name(),
        "undoSeconds": prefs_mod.undo_seconds(),
        "maxAttachmentBytes": settings.MAX_ATTACHMENT_BYTES,
        "identities": [{"address": a, "name": n} for a, n in MailIdentity.objects.order_by("address").values_list("address", "name")],
        "worker": {
            "state": "offline" if stale else ws.state,
            "detail": ws.detail if ws else "",
            "lastError": ws.last_error if ws else "",
            "lastErrorAt": iso(ws.last_error_at) if ws else None,
            "heartbeat": iso(ws.heartbeat) if ws else None,
        },
        "pendingOps": OutboxOp.objects.filter(status=OpStatus.PENDING).count(),
        "failedOps": OutboxOp.objects.filter(status=OpStatus.FAILED, finished__gte=timezone.now() - timedelta(days=1)).count(),
    }


@api(("GET", "POST"))
def folders(request):
    if request.method == "POST":
        name = str(body(request).get("name", "")).strip()
        if not name or len(name) > 200 or any(c in name for c in "\r\n\x00*%"):
            raise ApiError("Invalid folder name.")
        if Folder.objects.filter(name__iexact=name).exists():
            raise ApiError("A folder with that name already exists.")
        f = Folder.objects.create(name=name, needs_create=True, exists_on_server=False, initial_sync_done=True)
        from .. import outbox

        outbox.enqueue("create_folder", folder=f.pk)
        return folder_json(f)

    # Unread *conversations* per folder (like Gmail), not unread messages.
    # ThreadFolder has one row per (folder, conversation): plain index counts.
    unread = dict(
        ThreadFolder.objects.filter(unread=True).values("folder_id")
        .annotate(n=Count("id")).values_list("folder_id", "n")
    )
    totals = dict(
        ThreadFolder.objects.values("folder_id").annotate(n=Count("id")).values_list("folder_id", "n")
    )
    fs = sorted(Folder.objects.filter(selectable=True), key=lambda f: (ROLE_ORDER.get(f.role, 7), f.name.lower()))
    starred = Thread.objects.filter(starred=True).count()
    return {
        "folders": [folder_json(f, unread.get(f.id, 0), totals.get(f.id, 0)) for f in fs],
        "labels": [label_json(lb) for lb in Label.objects.all()],
        "starred": starred,
    }


@api(("POST",))
def check_now(request):
    """Ask the sync worker to look for new mail right away (Inbox, or ?folder=)."""
    from .. import outbox

    fid = int_or_none(body(request).get("folder"))
    folder = Folder.objects.filter(pk=fid).first() if fid else Folder.objects.filter(role=FolderRole.INBOX).first()
    if folder is None:
        return {"ok": True, "queued": False}
    if not OutboxOp.objects.filter(kind="check", status=OpStatus.PENDING, payload__folder=folder.pk).exists():
        outbox.enqueue("check", folder=folder.pk)
    return {"ok": True, "queued": True}


@api(("POST",))
def folder_read_all(request, pk: int):
    """Mark every unread message in a folder as read (here and on the server)."""
    folder = Folder.objects.get(pk=pk)
    ids = list(Message.objects.filter(folder=folder, seen=False).values_list("id", flat=True))
    for i in range(0, len(ids), 1000):
        chunk = list(Message.objects.filter(pk__in=ids[i:i + 1000]))
        actions.set_flags(chunk, add=["\\Seen"])
    return {"ok": True, "count": len(ids)}


@api(("GET", "POST"))
def labels(request):
    if request.method == "POST":
        data = body(request)
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ApiError("Invalid label name.")
        lb = labels_mod.get_or_create(name)
        if "color" in data:
            lb.color = str(data["color"])[:16]
            lb.save(update_fields=["color"])
        return label_json(lb)
    return [label_json(lb) for lb in Label.objects.all()]


@api(("PATCH", "DELETE"))
def label_detail(request, pk: int):
    lb = Label.objects.get(pk=pk)
    if request.method == "DELETE":
        msgs = list(lb.messages.all())
        actions.set_labels(msgs, remove=[lb])
        lb.delete()
        return {"ok": True}
    data = body(request)
    if "color" in data:
        lb.color = str(data["color"])[:16]
    lb.save()
    return label_json(lb)


# --- thread list --------------------------------------------------------------

ROLE_VIEWS = {r.value for r in FolderRole if r.value and r.value != FolderRole.ALL}


def resolve_view(view: str) -> str:
    """'inbox', 'sent', … (folder roles) -> 'folder:<id>', so a client can ask
    for its Inbox without first loading the folder list."""
    if view in ROLE_VIEWS:
        f = Folder.objects.filter(role=view).only("id").first()
        if f is None:
            raise ApiError("No such folder.", status=404)
        return f"folder:{f.id}"
    return view


def _folder_page(fid: int | None, unread_only: bool, cursor: str | None, limit: int) -> list[Thread]:
    """A folder's conversations, newest first, read from the ThreadFolder index."""
    rows = ThreadFolder.objects.filter(folder_id=fid)
    if unread_only:
        rows = rows.filter(unread=True)
    if cursor:
        dt, tid = _parse_cursor(cursor)
        rows = rows.filter(Q(last_date__lt=dt) | Q(last_date=dt, thread_id__lt=tid))
    ids = list(rows.order_by("-last_date", "-thread_id").values_list("thread_id", flat=True)[:limit])
    by_id = Thread.objects.in_bulk(ids)
    return [by_id[i] for i in ids if i in by_id]


def _parse_cursor(cursor: str):
    try:
        ts, tid = cursor.rsplit("|", 1)
        return datetime.fromisoformat(ts), int(tid)
    except ValueError:
        raise ApiError("Bad cursor.") from None


def _thread_queryset(view: str, q: str):
    qs = Thread.objects.all()
    if q:
        return qs.filter(pk__in=search.thread_ids_for(q))
    if view.startswith("folder:"):
        fid = int_or_none(view.split(":", 1)[1])
        return qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), folder_id=fid)))
    if view.startswith("label:"):
        lid = int_or_none(view.split(":", 1)[1])
        return qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), labels__id=lid)))
    hidden = [FolderRole.TRASH, FolderRole.JUNK]
    if view == "starred":
        return qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), flagged=True).exclude(folder__role__in=hidden)))
    if view == "all":
        return qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk")).exclude(folder__role__in=hidden)))
    raise ApiError("Unknown view.")


def _view_total(view: str, q: str, unread_only: bool) -> int:
    if view.startswith("folder:") and not q:
        rows = ThreadFolder.objects.filter(folder_id=int_or_none(view.split(":", 1)[1]))
        return (rows.filter(unread=True) if unread_only else rows).count()
    qs = _thread_queryset(view, q)
    if unread_only:
        qs = qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), seen=False)))
    return qs.count()


def _threads_json(page: list[Thread], q: str = "") -> list[dict]:
    folders_by_thread: dict[int, list[int]] = {}
    for tid, fid in ThreadFolder.objects.filter(thread_id__in=[t.id for t in page]).values_list("thread_id", "folder_id"):
        folders_by_thread.setdefault(tid, []).append(fid)
    ids = [t.id for t in page]
    snoozes = snooze.active_for_threads(ids)
    fups = followups.open_for_threads(ids)
    muted = mute_mod.muted_thread_ids(ids)
    pkgs = _package_chips(ids)
    me = my_addresses()
    out = [thread_json(t, folders_by_thread, snoozes, fups, muted, pkgs, me) for t in page]
    if q:
        found = search.hits(q, ids)
        for t in out:
            t["hit"] = found.get(t["id"], "")
    return out


@api()
def threads(request):
    view = resolve_view(request.GET.get("view", ""))
    q = request.GET.get("q", "").strip()[:500]
    unread_only = request.GET.get("unread") == "1"
    cursor = request.GET.get("cursor")
    by_relevance = bool(q) and request.GET.get("sort") == "relevance"
    next_cursor = None
    ranked = search.ranked_thread_ids(q) if by_relevance else None
    if ranked is not None:
        # Relevance: the ranking is computed once per request; the cursor is an offset into it.
        if unread_only:
            unread = set(Message.objects.filter(thread_id__in=ranked, seen=False).values_list("thread_id", flat=True))
            ranked = [t for t in ranked if t in unread]
        offset = int_or_none((cursor or "").removeprefix("o:")) or 0
        ids = ranked[offset: offset + PAGE]
        by_id = Thread.objects.in_bulk(ids)
        page = [by_id[i] for i in ids if i in by_id]
        if offset + PAGE < len(ranked):
            next_cursor = f"o:{offset + PAGE}"
        total = len(ranked) if not cursor else None
    else:
        if view.startswith("folder:") and not q:
            page = _folder_page(int_or_none(view.split(":", 1)[1]), unread_only, cursor, PAGE + 1)
        else:
            qs = _thread_queryset(view, q)
            if unread_only:
                qs = qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), seen=False)))
            qs = qs.order_by("-last_date", "-id")
            if cursor:
                dt, tid = _parse_cursor(cursor)
                qs = qs.filter(Q(last_date__lt=dt) | Q(last_date=dt, id__lt=tid))
            page = list(qs[: PAGE + 1])
        more = len(page) > PAGE
        page = page[:PAGE]
        next_cursor = f"{page[-1].last_date.isoformat()}|{page[-1].id}" if more and page[-1].last_date else None
        # How many there are in all ("Select all 1,234 conversations"): first page only.
        total = None if cursor else (len(page) if not more else _view_total(view, q, unread_only))
    return {"threads": _threads_json(page, q), "next": next_cursor, "total": total}


@api()
def search_suggest(request):
    """Everything the search box shows while you type: people, labels, folders and the best
    few conversations, in one request."""
    q = request.GET.get("q", "")[:300]
    op, partial = search.last_token(q)
    people = search.contacts(partial) if op in ("", "from", "to", "cc", "bcc") and partial else []
    labels = ([label_json(lb) for lb in Label.objects.filter(name__icontains=partial)[:4]]
              if partial and op in ("", "label") else [])
    folders = ([folder_json(f) for f in Folder.objects.filter(name__icontains=partial).exclude(role=FolderRole.ALL)[:4]]
               if partial and op in ("", "in") else [])
    found, total = [], 0
    if q.strip():
        ranked = search.ranked_thread_ids(q, limit=500)
        if ranked is None:
            qs = _thread_queryset("", q.strip()).order_by("-last_date", "-id")
            ids = list(qs.values_list("id", flat=True)[:6])
            total = qs.count()
        else:
            ids, total = ranked[:6], len(ranked)
        by_id = Thread.objects.in_bulk(ids)
        found = _threads_json([by_id[i] for i in ids if i in by_id], q.strip())
    return {"people": people, "labels": labels, "folders": folders, "threads": found, "total": total}


@api()
def thread_detail(request, pk: int):
    t = Thread.objects.get(pk=pk)
    msgs = list(
        Message.objects.filter(thread=t)
        .select_related("folder", "routed_by_block")
        .prefetch_related("attachments", "labels")
        .order_by("sort_date", "id")
    )
    # Collapse identical copies (same Message-ID and same bytes) in several
    # folders; different bytes under a duplicate Message-ID are kept.
    priority = {FolderRole.TRASH: 3, FolderRole.JUNK: 2}
    best: dict[tuple, Message] = {}
    for m in msgs:
        k = (m.message_key, m.blob_id)
        if k not in best or priority.get(m.folder.role, 0) < priority.get(best[k].folder.role, 0):
            best[k] = m
    unique = sorted(best.values(), key=lambda m: (m.sort_date, m.id))
    keys = [m.message_key for m in unique]
    drafts = dict(
        Draft.objects.filter(message_id__in=keys, status__in=[DraftStatus.EDITING, DraftStatus.FAILED])
        .values_list("message_id", "id")
    )
    keys = {m.message_key for m in msgs}
    ships = [shipment_json(s) for s in _recent_shipments() if s.thread_id == t.id or keys.intersection(s.message_keys)]
    scheduled = [
        {"id": d.id, "sendAt": iso(d.send_at), "to": d.to_addrs, "mode": d.mode}
        for d in Draft.objects.filter(status=DraftStatus.SCHEDULED, in_reply_to__thread=t).order_by("send_at")
    ]
    return {
        "tasks": tasks_for_keys({m.message_key for m in msgs}),
        "scheduled": scheduled,
        "packages": ships,
        "thread": thread_json(t, snoozes=snooze.active_for_threads([t.id]), fups=followups.open_for_threads([t.id]),
                              muted=mute_mod.muted_thread_ids([t.id])),
        "messages": [message_json(m, drafts) for m in unique],
    }


# --- actions -----------------------------------------------------------------

THREAD_ACTIONS = {"read", "unread", "star", "unstar", "archive", "trash", "move", "spam", "not_spam",
                  "delete_forever", "label_add", "label_remove", "inbox", "snooze", "unsnooze",
                  "mute", "unmute"}


MAX_BULK = 20000


def _view_thread_ids(view: str, q: str, unread_only: bool) -> list[int]:
    view = resolve_view(view) if view else view
    if view.startswith("folder:") and not q:
        rows = ThreadFolder.objects.filter(folder_id=int_or_none(view.split(":", 1)[1]))
        if unread_only:
            rows = rows.filter(unread=True)
        return list(rows.order_by("-last_date").values_list("thread_id", flat=True)[:MAX_BULK])
    qs = _thread_queryset(view, q)
    if unread_only:
        qs = qs.filter(Exists(Message.objects.filter(thread=OuterRef("pk"), seen=False)))
    return list(qs.order_by("-last_date").values_list("id", flat=True)[:MAX_BULK])


@api(("POST",))
def thread_actions(request):
    data = body(request)
    action = data.get("action")
    if action not in THREAD_ACTIONS:
        raise ApiError("Unknown action.")
    scope = data.get("all")
    if isinstance(scope, dict):
        # "Select all N conversations in this view" (not just the loaded page).
        if action in ("delete_forever", "snooze", "move", "spam"):
            raise ApiError("Select conversations one page at a time for this action.")
        ids = _view_thread_ids(str(scope.get("view", "")), str(scope.get("q", ""))[:500], bool(scope.get("unread")))
    else:
        ids = [int(i) for i in data.get("ids", [])][:500]
    context = Folder.objects.filter(pk=int_or_none(data.get("context"))).first() if data.get("context") else None
    result: dict = {"ok": True, "count": len(ids)}
    if action in ("read", "unread"):
        # One flag change for all of them, not one per conversation.
        want_seen = action == "read"
        for i in range(0, len(ids), 500):
            target = list(Message.objects.filter(thread_id__in=ids[i:i + 500], seen=not want_seen))
            for j in range(0, len(target), 1000):
                chunk = target[j:j + 1000]
                actions.set_flags(chunk, **({"add": ["\\Seen"]} if want_seen else {"remove": ["\\Seen"]}))
        return result
    for t in Thread.objects.filter(pk__in=ids):
        msgs = list(Message.objects.filter(thread=t).select_related("folder"))
        if action == "star":
            live = [m for m in msgs if m.folder.role not in (FolderRole.TRASH, FolderRole.JUNK)] or msgs
            latest = max(live, key=lambda m: (m.sort_date, m.id))
            if not latest.flagged:
                actions.set_flags([latest], add=["\\Flagged"])
        elif action == "unstar":
            actions.set_flags([m for m in msgs if m.flagged], remove=["\\Flagged"])
        elif action == "archive":
            actions.archive(t, context)
        elif action == "inbox":
            src = [m for m in msgs if m.folder.role in (FolderRole.ARCHIVE, "")] if context is None else [m for m in msgs if m.folder_id == context.pk]
            actions.move_messages(src, actions.role_folder(FolderRole.INBOX))
        elif action == "trash":
            actions.trash(t, context)
        elif action == "move":
            dest = Folder.objects.get(pk=int_or_none(data.get("dest")))
            actions.move_thread(t, context, dest)
        elif action == "spam":
            try:
                result.update(actions.report_spam(t, context, block=str(data.get("block", ""))))
            except (spam.BlockError, actions.ActionError) as exc:
                raise ApiError(str(exc)) from exc
        elif action == "not_spam":
            result.update(actions.not_spam(t, context))
        elif action == "delete_forever":
            target = [m for m in msgs if (context is None or m.folder_id == context.pk)
                      and m.folder.role in (FolderRole.TRASH, FolderRole.JUNK)]
            try:
                actions.delete_forever(target)
            except actions.ActionError as exc:
                raise ApiError(str(exc)) from exc
        elif action == "snooze":
            try:
                until = datetime.fromisoformat(str(data.get("until", "")))
            except ValueError:
                raise ApiError("Pick a time to snooze until.") from None
            try:
                s = snooze.snooze_thread(t, context, until)
            except snooze.SnoozeError as exc:
                raise ApiError(str(exc)) from exc
            result["until"] = iso(s.wake_at)
        elif action == "mute":
            mute_mod.mute(t)
        elif action == "unmute":
            dest = Folder.objects.filter(pk=int_or_none(data.get("dest"))).first() if data.get("dest") else None
            mute_mod.unmute(t, restore_to=dest)
        elif action == "unsnooze":
            for s in snooze.active_for_threads([t.id]).values():
                snooze.unsnooze(s, reason="manual")
        elif action in ("label_add", "label_remove"):
            lb = Label.objects.get(pk=int_or_none(data.get("label")))
            if action == "label_add":
                actions.set_labels(msgs, add=[lb])
            else:
                actions.set_labels(msgs, remove=[lb])
    return result


@api(("POST",))
def message_actions(request):
    data = body(request)
    action = data.get("action")
    msgs = list(Message.objects.filter(pk__in=[int(i) for i in data.get("ids", [])][:500]).select_related("folder"))
    flag_map = {
        "read": ({"add": ["\\Seen"]}), "unread": ({"remove": ["\\Seen"]}),
        "star": ({"add": ["\\Flagged"]}), "unstar": ({"remove": ["\\Flagged"]}),
    }
    if action in flag_map:
        actions.set_flags(msgs, **flag_map[action])
    elif action == "trash":
        actions.move_messages([m for m in msgs if m.folder.role != FolderRole.TRASH], actions.role_folder(FolderRole.TRASH))
    else:
        raise ApiError("Unknown action.")
    return {"ok": True}


# --- message content ---------------------------------------------------------

def _message(pk: int) -> Message:
    return Message.objects.select_related("folder").get(pk=pk)


_INVISIBLE = re.compile(r"(?is)<(style|head|title|script)\b[^>]*>.*?</\1\s*>|<!--.*?-->")
_TAGS = re.compile(r"(?s)<[^>]*>")
_VISUAL = re.compile(r"(?i)<(img|video|svg|picture|hr)\b|background(-image)?\s*[:=]\s*['\"]?\s*url")


def _shows_anything(html: str) -> bool:
    """Whether sanitized HTML has visible text or pictures."""
    if _VISUAL.search(html):
        return True
    import html as html_lib

    text = html_lib.unescape(_TAGS.sub(" ", _INVISIBLE.sub(" ", html)))
    return bool(text.replace("\xa0", " ").replace("\u200b", "").replace("\u200c", "").strip())


@api()
def message_body(request, pk: int):
    m = _message(pk)
    raw = store.get(m.blob_id)
    pm = parsing.parse_message(raw)
    trusted = TrustedImageSender.objects.filter(address=m.from_addr).exists()
    load = request.GET.get("images") == "1" or trusted or bool(prefs_mod.get()["load_images"])
    # Never auto-load images for risky mail, even from a "trusted" sender.
    if m.risk_level == "high" and request.GET.get("images") != "1":
        load = False
    cid_map = {a.content_id: a.id for a in m.attachments.all() if a.content_id}
    # colors=dark|light fits the email to Kern's page in that theme; anything else: as sent.
    theme = request.GET.get("colors", "")
    theme = theme if theme in ("dark", "light") else ""
    how = "none"
    if pm.html:
        res = sanitize.sanitize_html(pm.html, message_pk=m.pk, load_images=load, cid_map=cid_map, theme=theme)
        html, remote, how = res.html, res.remote_images, res.colors
        if not remote and not _shows_anything(html):
            html = None  # an empty HTML part (e.g. only attachments): don't draw a blank page
    else:
        html, remote = None, 0
    return {
        "html": html,
        "colors": how,
        "text": (pm.text or "") if html is None else None,
        "textHtml": sanitize.linkify_text(pm.text or "") if html is None else None,
        "remoteImages": remote,
        "imagesLoaded": load and remote > 0,
        "trustedSender": trusted,
    }


@api()
def message_headers(request, pk: int):
    """The raw header block, for inspecting suspicious mail yourself."""
    m = _message(pk)
    raw = store.get(m.blob_id)
    end = raw.find(b"\r\n\r\n")
    if end < 0:
        end = raw.find(b"\n\n")
    head = raw[: end if end >= 0 else min(len(raw), 200_000)][:200_000]
    text, _ = parsing.decode_bytes(head, "utf-8")
    return {"headers": text.replace("\r\n", "\n")}


@api(("POST",))
def message_unsubscribe(request, pk: int):
    from .. import unsubscribe

    m = _message(pk)
    o = unsubscribe.options(m)
    if o is None:
        raise ApiError("This message has no unsubscribe option.")
    if not o.one_click:
        return {"done": False, "url": o.https, "mailto": o.mailto}
    try:
        unsubscribe.one_click(o.https)
    except imgproxy.ProxyError as exc:
        return {"done": False, "url": o.https, "mailto": o.mailto, "error": str(exc)}
    return {"done": True, "host": urlsplit(o.https).hostname}


@api()
def message_raw(request, pk: int):
    m = _message(pk)
    resp = HttpResponse(store.get(m.blob_id), content_type="application/octet-stream")
    resp["Content-Disposition"] = content_disposition_header(True, f"message-{m.pk}.eml")
    resp["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return resp


def _attachment(pk: int, aid: int):
    m = _message(pk)
    att = Attachment.objects.get(pk=aid, message=m)
    part = parsing.find_part(store.get(m.blob_id), att.part_index)
    if part is None:
        raise ApiError("Attachment not found.", 404, "not_found")
    return m, att, part


@api()
def attachment(request, pk: int, aid: int):
    m, att, part = _attachment(pk, aid)
    data = part.payload()
    want_inline = request.GET.get("inline") == "1"
    media = _media_type(att.content_type, att.filename) if want_inline else None
    inline = want_inline and (_previewable(att.content_type) or media is not None)
    # SECURITY: only known-safe raster images and audio/video are ever served
    # with their own type; anything else is a download with a generic type, so
    # the browser never renders attacker content (HTML, SVG, PDF) on our origin.
    ctype = (media or att.content_type.lower()) if inline else "application/octet-stream"
    resp = _ranged(request, data, ctype) if media else HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = content_disposition_header(not inline, att.filename)
    resp["Content-Security-Policy"] = "sandbox; default-src 'none'"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


_HEAD = re.compile(r"<head\b[^>]*>(.*?)</head\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_TAG = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.IGNORECASE)


@api()
def attachment_html(request, pk: int, aid: int):
    """An HTML attachment, cleaned by the same sanitizer as email bodies, for
    the viewer's script-less sandboxed frame. Remote images stay blocked
    unless asked for (and always for high-risk mail unless asked)."""
    m, att, part = _attachment(pk, aid)
    if _preview(att.content_type, att.filename, att.size) != "html":
        raise ApiError("This attachment is not an HTML file.", 400, "not_html")
    data = part.payload()[:HTML_MAX]
    charset = part.charset
    if not charset:
        hit = _META_CHARSET.search(data[:4096])
        charset = hit.group(1).decode("ascii", "ignore") if hit else "utf-8"
    try:
        markup = data.decode(charset, "replace")
    except LookupError:
        markup = data.decode("utf-8", "replace")
    # A standalone page keeps its look in <head><style>, which the email
    # sanitizer drops with the rest of <head>: move those styles into the body.
    head = _HEAD.search(markup)
    if head:
        styles = "".join(_STYLE_TAG.findall(head.group(1)))
        markup = markup[:head.start()] + markup[head.end():]
        markup = styles + markup
    load = request.GET.get("images") == "1"
    res = sanitize.sanitize_html(markup, message_pk=m.pk, load_images=load)
    return {"html": res.html, "remoteImages": res.remote_images, "imagesLoaded": load and res.remote_images > 0}


@api()
def image_proxy(request):
    url = request.GET.get("u", "")
    if not imgproxy.verify(url, request.GET.get("s", "")):
        return HttpResponse(status=403)
    try:
        fetched = imgproxy.fetch(url)
    except imgproxy.ProxyError:
        return HttpResponse(status=502)
    resp = HttpResponse(fetched.body, content_type=fetched.content_type)
    resp["Content-Security-Policy"] = "sandbox; default-src 'none'"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@api(("GET", "POST"))
def followup_list(request):
    from ..models import FollowUp

    if request.method == "POST":
        data = body(request)
        t = Thread.objects.get(pk=int_or_none(data.get("threadId")))
        try:
            until = datetime.fromisoformat(str(data.get("until", "")))
            f = followups.create_for_thread(t, until)
        except ValueError as exc:
            raise ApiError(str(exc) if isinstance(exc, followups.FollowUpError) else "Pick a time.") from exc
        return followup_json(f)
    out = []
    for f in FollowUp.objects.filter(status__in=followups.OPEN).order_by("status", "due_at")[:200]:
        followups._thread_id(f)
        out.append(followup_json(f))
    return out


@api(("POST",))
def followup_action(request, pk: int):
    from ..models import FollowUp, FollowUpStatus

    f = FollowUp.objects.get(pk=pk)
    data = body(request)
    if data.get("action") == "done":  # "I've dealt with it": its task is completed
        followups.close(f, FollowUpStatus.DONE)
    elif data.get("action") == "cancel":  # "don't nudge me after all": its task is removed
        followups.close(f, FollowUpStatus.CANCELLED)
    elif data.get("action") == "later":
        try:
            until = datetime.fromisoformat(str(data.get("until", "")))
        except ValueError:
            raise ApiError("Pick a time.") from None
        if timezone.is_naive(until) or until <= timezone.now():
            raise ApiError("Pick a time in the future.")
        followups.move(f, until)
    else:
        raise ApiError("Unknown action.")
    return followup_json(f)


@api()
def sender_info(request):
    from ..models import Correspondent

    addr = request.GET.get("addr", "").strip().lower()
    if "@" not in addr:
        raise ApiError("Invalid address.")
    c = Correspondent.objects.filter(address=addr).first()
    received = Message.objects.filter(from_addr=addr).values("message_key").distinct().count()
    me = list(my_addresses())
    you_sent = Message.objects.filter(from_addr__in=me, search_recipients__icontains=addr).values("message_key").distinct().count()
    first = Message.objects.filter(from_addr=addr).order_by("sort_date").values_list("sort_date", flat=True).first()
    rule = spam.matching_rule(addr)
    dom = spam.domain_of(addr)
    from ..risk.domains import to_ascii, to_unicode

    return {
        "addr": addr,
        "name": c.name if c else "",
        "domain": to_unicode(dom),
        "domainAscii": to_ascii(dom),
        "received": received,
        "sent": you_sent,
        "firstSeen": iso(first or (c.first_seen if c else None)),
        "blocked": {"kind": rule.kind, "value": rule.value} if rule else None,
        "trustedImages": TrustedImageSender.objects.filter(address=addr).exists(),
        "domainBlockAllowed": bool(dom) and not spam.is_shared_provider(dom),
    }


def _recent_shipments():
    from ..models import Shipment

    since = timezone.now() - timedelta(days=90)
    return list(Shipment.objects.filter(hidden=False, status_at__gte=since).order_by("status_at")[:300])


def _package_chips(thread_ids: list[int]) -> dict:
    """thread id -> newest package status, for every thread holding an email
    about that package (the shop's and the carrier's). Bounded: recent
    shipments only, one query on their message keys."""
    from .. import packages as pk

    ships = _recent_shipments()
    if not ships or not thread_ids:
        return {}
    by_key = {k: s for s in ships for k in s.message_keys}
    out = {}
    rows = Message.objects.filter(thread_id__in=thread_ids, message_key__in=list(by_key)).values_list("thread_id", "message_key")
    now = timezone.now()

    def chip(s):
        if _settled(s, now):
            return {"status": "delivered", "label": "Probably delivered"}
        return {"status": s.status, "label": pk.STATUS_LABEL.get(s.status, s.status)}

    for tid, key in sorted(rows, key=lambda r: by_key[r[1]].status_at):
        out[tid] = chip(by_key[key])
    for s in ships:  # thread set directly (e.g. after a resync changed keys)
        if s.thread_id in thread_ids and s.thread_id not in out:
            out[s.thread_id] = chip(s)
    return out


def shipment_json(s, assumed: bool = False) -> dict:
    from .. import packages

    tid = s.thread_id
    if not tid and s.message_keys:
        tid = Message.objects.filter(message_key__in=s.message_keys, thread__isnull=False).values_list("thread_id", flat=True).first()
    carrier = packages.CARRIERS.get(s.carrier)
    status = "delivered" if assumed else s.status
    return {
        "id": s.id, "number": s.number, "carrier": s.carrier, "carrierName": carrier.name if carrier else s.carrier,
        "status": status, "statusLabel": "Probably delivered" if assumed else packages.STATUS_LABEL.get(s.status, s.status),
        "statusAt": iso(s.status_at), "step": packages.STATUS_STEP.get(status, 1), "assumed": assumed,
        "expected": s.expected.isoformat() if s.expected else None, "expectedText": s.expected_text,
        "merchant": s.merchant, "subject": s.subject, "trackUrl": packages.track_url(s.carrier, s.number),
        "threadId": tid, "hidden": s.hidden,
        "live": s.live, "location": s.location, "checkedAt": iso(s.checked_at), "events": (s.live_events or [])[:12],
        "route": s.route or {},
        "trackNote": s.track_note,
    }


def _settled(s, now) -> bool:
    """No live tracking and no news long after it was due: it almost certainly arrived
    (shops rarely email "delivered"). Shown as probably delivered instead of on the way."""
    if s.live or s.status in ("delivered", "exception", "ready_for_pickup"):
        return False
    quiet = lambda days: bool(s.status_at) and s.status_at < now - timedelta(days=days)  # noqa: E731
    if s.status == "out_for_delivery":
        return quiet(2)
    if s.expected:
        return s.expected < timezone.localdate() - timedelta(days=2) and quiet(2)
    return quiet(14)


def package_buckets(now=None) -> tuple[list, list]:
    """(on the way, delivered in the last two weeks) as JSON."""
    from ..models import Shipment

    now = now or timezone.now()
    recent = now - timedelta(days=14)
    qs = Shipment.objects.filter(hidden=False)
    active, done = [], []
    for s in qs.exclude(status="delivered").filter(status_at__gte=now - timedelta(days=60)).order_by("expected", "-status_at")[:150]:
        if _settled(s, now):
            if (s.expected and s.expected >= recent.date()) or (s.status_at and s.status_at >= recent):
                done.append(shipment_json(s, assumed=True))
        else:
            active.append(shipment_json(s))
    done += [shipment_json(s) for s in qs.filter(status="delivered", status_at__gte=recent).order_by("-status_at")[:50]]
    done.sort(key=lambda p: p["statusAt"] or "", reverse=True)
    return active[:100], done[:50]


@api()
def packages_list(request):
    from .. import tracking

    from .. import geo

    active, done = package_buckets()
    return {"active": active, "delivered": done, "tracking": tracking.settings_json(), "map": geo.map_json()}


@api(("GET", "POST"))
def packages_map(request):
    """The map's tiles: {provider, key?, custom?: {light, dark, attribution}} (mail/geo.py MAP_SOURCES).
    The older {key} alone switches to MapTiler, or back to OpenStreetMap when empty."""
    from .. import geo

    if request.method == "POST":
        data = body(request)
        try:
            if "provider" not in data:
                return geo.set_maptiler_key(str(data.get("key") or ""))
            return geo.configure_map(str(data["provider"]), data.get("key") if "key" in data else None,
                                     data.get("custom") if isinstance(data.get("custom"), dict) else None)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
    return geo.map_json()


@api(("GET", "POST"))
def private_ai_view(request):
    """The private model (mail/private_ai.py): {baseUrl, model, key?, timeout, sortMail}. GET also
    says whether it answers right now (online) and which models it offers."""
    from .. import private_ai

    if request.method == "POST":
        try:
            return private_ai.configure(body(request))
        except private_ai.PrivateAIError as exc:
            raise ApiError(str(exc)) from exc
    return private_ai.settings_json(check=True)


@api(("POST",))
def private_ai_test(request):
    """Sort a sample promotional email with the private model now; says what it answered."""
    from .. import private_ai

    if not private_ai.configured():
        raise ApiError("Set up the private model first.")
    return {**private_ai.test_sample(), "settings": private_ai.settings_json(check=False)}


@api(("POST",))
def private_ai_feedback(request, pk: int):
    """{text}: the owner's correction on how the private model sorted this message. It becomes a
    rule the model reads before every email."""
    from .. import private_ai

    m = _message(pk)
    try:
        line = private_ai.feedback(m, body(request).get("text", ""))
    except private_ai.PrivateAIError as exc:
        raise ApiError(str(exc)) from exc
    return {"rule": line, "guidance": private_ai.settings_json(check=False)["guidance"]}


@api(("GET", "POST"))
def packages_tracking(request):
    """Live tracking settings: {provider: "parcels"|"trackingmore"|"scraper"|"", key?, country?, limit?,
    scraper?: {url, fallbacks}}. key "" forgets the stored key, a missing key keeps it."""
    from .. import tracking

    if request.method == "POST":
        data = body(request)
        try:
            out = tracking.configure(str(data.get("provider") or ""), data.get("key") if "key" in data else None,
                                     data.get("country") if "country" in data else None,
                                     int_or_none(data.get("limit")) if data.get("limit") else None,
                                     data.get("scraper") if isinstance(data.get("scraper"), dict) else None)
            if out["provider"]:
                tracking.check_key()  # quick: the service answers (and takes the key); no lookups
                tracking.kick()  # the mail worker checks every package within seconds
                out = tracking.settings_json()
        except tracking.TrackingError as exc:
            raise ApiError(str(exc)) from exc
        return out
    return tracking.settings_json()


@api(("POST",))
def package_action(request, pk: int):
    from .. import tracking
    from ..models import Shipment

    s = Shipment.objects.get(pk=pk)
    action = body(request).get("action")
    if action == "refresh":
        try:
            tracking.refresh([s], force=True)
        except tracking.TrackingError as exc:
            raise ApiError(str(exc)) from exc
        s.refresh_from_db()
        return shipment_json(s)
    if action == "hide":
        s.hidden = True
    elif action == "unhide":
        s.hidden = False
    elif action == "delivered":
        s.status, s.status_at = "delivered", timezone.now()
    else:
        raise ApiError("Unknown action.")
    s.save()
    return shipment_json(s)


# --- reply templates -------------------------------------------------------

MAX_TEMPLATES = 200
MAX_TEMPLATE_HTML = 100_000


def template_json(t) -> dict:
    return {"id": t.id, "name": t.name, "subject": t.subject, "bodyHtml": t.body_html, "uses": t.uses,
            "updated": iso(t.updated)}


def _apply_template(t, data: dict) -> None:
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ApiError("Give the template a name.")
        t.name = name[:120]
    if "subject" in data:
        t.subject = str(data.get("subject") or "").replace("\r", " ").replace("\n", " ")[:500]
    if "bodyHtml" in data:
        html = str(data.get("bodyHtml") or "")
        if len(html) > MAX_TEMPLATE_HTML:
            raise ApiError("That template is too long.")
        t.body_html = sending.clean_compose_html(html)


@api(("GET", "POST"))
def templates(request):
    from ..models import Template

    if request.method == "GET":
        return [template_json(t) for t in Template.objects.order_by("-uses", "name")[:MAX_TEMPLATES]]
    if Template.objects.count() >= MAX_TEMPLATES:
        raise ApiError("You have too many templates. Delete some first.")
    t = Template()
    _apply_template(t, {"name": "", **body(request)})
    t.save()
    return template_json(t)


@api(("PATCH", "DELETE", "POST"))
def template_detail(request, pk: int):
    from ..models import Template

    t = Template.objects.get(pk=pk)
    if request.method == "DELETE":
        t.delete()
        return {"ok": True}
    if request.method == "POST":  # "used": ranks frequent templates first
        Template.objects.filter(pk=pk).update(uses=models.F("uses") + 1)
        t.refresh_from_db()
        return template_json(t)
    _apply_template(t, body(request))
    t.save()
    return template_json(t)


# --- attachments browser ---------------------------------------------------

FILE_KINDS = {
    "image": Q(content_type__istartswith="image/"),
    "pdf": Q(content_type__iexact="application/pdf") | Q(filename__iendswith=".pdf"),
    "doc": (Q(content_type__icontains="word") | Q(content_type__icontains="spreadsheet")
            | Q(content_type__icontains="presentation") | Q(content_type__icontains="opendocument")
            | Q(content_type__icontains="excel") | Q(content_type__icontains="powerpoint")
            | Q(content_type__iexact="text/csv") | Q(content_type__iexact="text/plain")),
    "media": (Q(content_type__istartswith="audio/") | Q(content_type__istartswith="video/")
              | Q(filename__iregex=r"\.(" + "|".join(MEDIA_EXT) + r")$")),
    "archive": (Q(content_type__icontains="zip") | Q(content_type__icontains="compressed")
                | Q(content_type__icontains="tar") | Q(content_type__icontains="7z")),
}


def _file_kind(a) -> str:
    ct, fn = a.content_type.lower(), a.filename.lower()
    if ct.startswith("image/"):
        return "image"
    if ct == "application/pdf" or fn.endswith(".pdf"):
        return "pdf"
    if ct.startswith(("audio/", "video/")) or _ext(fn) in MEDIA_EXT:
        return "media"
    if any(w in ct for w in ("zip", "compressed", "tar", "7z")):
        return "archive"
    if any(w in ct for w in ("word", "spreadsheet", "presentation", "opendocument", "excel", "powerpoint")) or ct in ("text/csv", "text/plain"):
        return "doc"
    return "other"


@api()
def attachments_list(request):
    """Every real (non-inline) attachment, newest first. Trash and Junk are
    left out. ?kind=image|pdf|doc|media|archive|other  ?q=filename or sender  ?before=<id>"""
    qs = (Attachment.objects.filter(inline=False)
          .exclude(message__folder__role__in=[FolderRole.TRASH, FolderRole.JUNK])
          .exclude(content_type__iexact="message/rfc822")
          .select_related("message"))
    kind = request.GET.get("kind", "")
    if kind in FILE_KINDS:
        qs = qs.filter(FILE_KINDS[kind])
    elif kind == "other":
        for q in FILE_KINDS.values():
            qs = qs.exclude(q)
    q = request.GET.get("q", "").strip()[:200]
    if q:
        qs = qs.filter(Q(filename__icontains=q) | Q(message__from_addr__icontains=q) | Q(message__from_name__icontains=q)
                       | Q(message__subject__icontains=q))
    before = int_or_none(request.GET.get("before"))
    if before:
        qs = qs.filter(id__lt=before)
    page = list(qs.order_by("-id")[:61])
    # The same file often sits in several folders (or came twice): show it once.
    seen, out = set(), []
    for a in page[:60]:
        m = a.message
        key = (m.message_key, a.filename, a.size)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": a.id, "messageId": m.id, "threadId": m.thread_id, "filename": a.filename, "size": a.size,
            "contentType": a.content_type, "kind": _file_kind(a), "previewable": _previewable(a.content_type),
            "preview": _preview(a.content_type, a.filename, a.size),
            "from": {"name": m.from_name, "addr": m.from_addr}, "subject": m.subject, "date": iso(m.sort_date),
            "risk": m.risk_level,
        })
    return {"files": out, "next": page[59].id if len(page) > 60 else None}


@api()
def snoozes(request):
    from ..models import Snooze, SnoozeStatus

    return [
        {"id": s.id, "threadId": s.thread_id, "subject": s.subject, "until": iso(s.wake_at)}
        for s in Snooze.objects.filter(status=SnoozeStatus.ACTIVE)[:500]
    ]


# --- block list / trusted senders / contacts / risk --------------------------

@api(("GET", "POST"))
def blocklist(request):
    if request.method == "POST":
        data = body(request)
        try:
            rule = spam.add_block(str(data.get("kind", "")), str(data.get("value", "")), str(data.get("note", "")))
        except spam.BlockError as exc:
            raise ApiError(str(exc)) from exc
        return {"id": rule.id, "kind": rule.kind, "value": rule.value}
    return [
        {"id": r.id, "kind": r.kind, "value": r.value, "note": r.note, "created": iso(r.created), "hits": r.hits}
        for r in BlockRule.objects.all()
    ]


@api(("DELETE",))
def blocklist_detail(request, pk: int):
    BlockRule.objects.filter(pk=pk).delete()
    return {"ok": True}


@api()
def block_check(request):
    addr = request.GET.get("addr", "").lower()
    dom = spam.domain_of(addr)
    return {"address": addr, "domain": dom, "domainBlockAllowed": bool(dom) and not spam.is_shared_provider(dom)}


@api(("GET", "POST"))
def trusted_senders(request):
    if request.method == "POST":
        addr = str(body(request).get("address", "")).strip().lower()
        if "@" not in addr:
            raise ApiError("Invalid address.")
        TrustedImageSender.objects.get_or_create(address=addr)
        return {"ok": True}
    return [{"id": t.id, "address": t.address} for t in TrustedImageSender.objects.order_by("address")]


@api(("DELETE",))
def trusted_sender_detail(request, pk: int):
    TrustedImageSender.objects.filter(pk=pk).delete()
    return {"ok": True}


@api()
def contacts(request):
    q = request.GET.get("q", "").strip()
    qs = Correspondent.objects.all()
    if q:
        qs = qs.filter(Q(address__icontains=q) | Q(name__icontains=q))
    qs = qs.order_by("-sent_count", "-received_count", "address")[:12]
    return [{"name": c.name, "addr": c.address} for c in qs]


@api()
def risk_rules(request):
    return risk.describe_rules()


# --- compose / drafts --------------------------------------------------------

def draft_json(d: Draft) -> dict:
    return {
        "id": d.id, "mode": d.mode, "to": d.to_addrs, "cc": d.cc_addrs, "bcc": d.bcc_addrs,
        "subject": d.subject, "bodyHtml": d.body_html, "status": d.status, "error": d.error,
        "sendAt": iso(d.send_at), "inReplyTo": d.in_reply_to_id, "updated": iso(d.updated),
        "followupAt": iso(d.followup_at),
        "from": d.from_addr,
        "uploads": [{"id": u.id, "filename": u.filename, "size": u.size, "contentType": u.content_type}
                    for u in d.uploads.all()],
        "forwardAttachments": [
            {"id": a.id, "filename": a.filename, "size": a.size, "contentType": a.content_type}
            for a in Attachment.objects.filter(pk__in=d.forward_attachment_ids or [])
        ],
    }


def _apply_draft_fields(d: Draft, data: dict) -> None:
    try:
        if "to" in data:
            d.to_addrs = sending.validate_recipients(data["to"])
        if "cc" in data:
            d.cc_addrs = sending.validate_recipients(data["cc"])
        if "bcc" in data:
            d.bcc_addrs = sending.validate_recipients(data["bcc"])
    except sending.ComposeError as exc:
        raise ApiError(str(exc)) from exc
    if "from" in data:
        addr = str(data.get("from") or "").strip()
        account_addr = _mail_cfg()["USERNAME"]
        if addr and addr.lower() != account_addr.lower() and addr.lower() not in my_addresses():
            raise ApiError("You can only send from your own addresses (Settings → Mail → Send mail as).")
        d.from_addr = "" if addr.lower() == account_addr.lower() else addr[:320]
    if "subject" in data:
        d.subject = str(data["subject"])[:2000]
    if "bodyHtml" in data:
        body_html = str(data["bodyHtml"])
        if len(body_html) > 5_000_000:
            raise ApiError("Message too long.")
        d.body_html = sending.clean_compose_html(body_html)
    if "followupAt" in data:
        raw = data.get("followupAt")
        if not raw:
            d.followup_at = None
        else:
            try:
                fa = datetime.fromisoformat(str(raw))
            except ValueError:
                raise ApiError("Invalid reminder time.") from None
            if timezone.is_naive(fa) or fa <= timezone.now():
                raise ApiError("The reminder must be in the future.")
            d.followup_at = fa
    if "forwardAttachments" in data and d.forward_attachments_of_id:
        allowed = set(Attachment.objects.filter(message_id=d.forward_attachments_of_id).values_list("id", flat=True))
        d.forward_attachment_ids = [int(i) for i in data["forwardAttachments"] if int(i) in allowed]


@api()
def compose_prefill(request):
    mode = request.GET.get("mode", "reply")
    if mode not in ("reply", "reply_all", "forward"):
        raise ApiError("Bad mode.")
    m = _message(int(request.GET.get("message", 0)))
    pm = parsing.parse_message(store.get(m.blob_id))
    if pm.html:
        quoted = sanitize.sanitize_html(pm.html, message_pk=m.pk, load_images=False).html
    else:
        quoted = parsing.text_to_html(pm.text)
    return sending.compose_prefill(m, mode, quoted)


@api(("GET", "POST"))
def drafts(request):
    if request.method == "GET":
        qs = Draft.objects.filter(status__in=[DraftStatus.EDITING, DraftStatus.FAILED, DraftStatus.QUEUED]).order_by("-updated")[:100]
        return [draft_json(d) for d in qs]
    data = body(request)
    d = Draft(message_id=sending.new_message_id(), mode=str(data.get("mode", "new"))[:16])
    reply_to = int_or_none(data.get("inReplyTo"))
    if reply_to:
        src = Message.objects.get(pk=reply_to)
        if d.mode in ("reply", "reply_all"):
            d.in_reply_to = src
            d.in_reply_to_key = src.message_id
            refs = list(src.references or [])
            if src.message_id and src.message_id not in refs:
                refs.append(src.message_id)
            d.references = refs[-30:]
        elif d.mode == "forward":
            d.forward_attachments_of = src
            d.in_reply_to = src
            d.forward_attachment_ids = list(src.attachments.filter(inline=False).values_list("id", flat=True))
    _apply_draft_fields(d, data)
    d.save()
    return draft_json(d)


@api(("GET", "PATCH", "DELETE"))
def draft_detail(request, pk: int):
    d = Draft.objects.get(pk=pk)
    if request.method == "GET":
        return draft_json(d)
    if request.method == "DELETE":
        if d.server_uid and d.server_folder_id:
            from .. import outbox

            outbox.enqueue("delete_server_draft", folder=d.server_folder_id,
                           uidvalidity=d.server_uidvalidity, uid=d.server_uid)
        for up in d.uploads.all():
            up.delete()
        d.delete()
        return {"ok": True}
    if d.status not in (DraftStatus.EDITING, DraftStatus.FAILED):
        raise ApiError("This message is being sent.", 409, "conflict")
    data = body(request)
    _apply_draft_fields(d, data)
    d.status = DraftStatus.EDITING
    d.save()
    if data.get("saveToServer"):
        from .. import outbox

        if not OutboxOp.objects.filter(kind="save_draft", status=OpStatus.PENDING, payload__draft=d.pk).exists():
            outbox.enqueue("save_draft", delay=2, draft=d.pk)
    return draft_json(d)


@api(("POST",))
def draft_send(request, pk: int):
    d = Draft.objects.get(pk=pk)
    data = body(request)
    if data:
        _apply_draft_fields(d, data)
        d.save()
    at = None
    if data.get("sendAt"):
        try:
            at = datetime.fromisoformat(str(data["sendAt"]))
        except ValueError:
            raise ApiError("Pick a valid time.") from None
        if timezone.is_naive(at):
            raise ApiError("Pick a valid time.")
        if at <= timezone.now():
            raise ApiError("That time has already passed.")
    try:
        sending.queue_send(d, at=at)
    except sending.ComposeError as exc:
        raise ApiError(str(exc)) from exc
    return draft_json(d)


@api(("POST",))
def draft_unschedule(request, pk: int):
    d = Draft.objects.get(pk=pk)
    if not sending.unschedule(d):
        raise ApiError("This message isn't scheduled any more; it may have been sent.", 409, "conflict")
    d.refresh_from_db()
    return draft_json(d)


@api()
def scheduled_list(request):
    qs = Draft.objects.filter(status=DraftStatus.SCHEDULED).select_related("in_reply_to").order_by("send_at")[:200]
    out = []
    for d in qs:
        j = draft_json(d)
        j["threadId"] = d.in_reply_to.thread_id if d.in_reply_to_id else None
        out.append(j)
    return out


@api(("POST",))
def draft_undo(request, pk: int):
    d = Draft.objects.get(pk=pk)
    if not sending.undo_send(d):
        raise ApiError("Too late to undo; the message was sent.", 409, "conflict")
    d.refresh_from_db()
    return draft_json(d)


@api(("POST",))
def draft_upload(request, pk: int):
    d = Draft.objects.get(pk=pk)
    files = request.FILES.getlist("file")
    if not files:
        raise ApiError("No file.")
    total = sum(u.size for u in d.uploads.all())
    out = []
    for f in files[:20]:
        if f.size > settings.MAX_ATTACHMENT_BYTES or total + f.size > settings.MAX_ATTACHMENT_BYTES:
            raise ApiError(f"Attachments are limited to {settings.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB in total.")
        data = f.read()
        total += len(data)
        sha = store.put_upload(data)
        name = parsing.safe_filename(f.name or "") or "attachment"
        up = Upload.objects.create(draft=d, filename=name, size=len(data), sha256=sha,
                                   content_type=sending.guess_type(name, f.content_type))
        out.append({"id": up.id, "filename": up.filename, "size": up.size, "contentType": up.content_type})
    return {"uploads": out}


@api(("DELETE",))
def draft_upload_detail(request, pk: int, uid: int):
    Upload.objects.filter(pk=uid, draft_id=pk).delete()
    return {"ok": True}


@api()
def draft_for_message(request, pk: int):
    """Open a draft stored on the server (e.g. written in another client)."""
    m = _message(pk)
    existing = Draft.objects.filter(message_id=m.message_id).exclude(status=DraftStatus.SENT).first() if m.message_id else None
    if existing:
        return draft_json(existing)
    pm = parsing.parse_message(store.get(m.blob_id))
    body_html = sending.clean_compose_html(pm.html) if pm.html else parsing.text_to_html(pm.text)
    d = Draft.objects.create(
        message_id=m.message_id or sending.new_message_id(),
        to_addrs=m.to_addrs, cc_addrs=m.cc_addrs, bcc_addrs=m.bcc_addrs, subject=m.subject,
        body_html=body_html, in_reply_to_key=m.in_reply_to, references=m.references,
        server_folder=m.server_folder, server_uidvalidity=m.uidvalidity, server_uid=m.uid,
    )
    return draft_json(d)


# --- live updates ------------------------------------------------------------
# Kern runs on threaded WSGI, so instead of a held-open event stream the app
# asks this cheap endpoint for news. With ?wait=<seconds> (at most LONG_POLL)
# the request is held until something happens, so new mail shows up within a
# fraction of a second of reaching the server without frequent polling.

LONG_POLL = 290.0  # Kern Mail on Android holds up to ~4.5 min; the web app asks for 20 s
LONG_POLL_TICK = 0.25  # first 20 s: answer within a quarter second
LONG_POLL_SLOW_TICK = 0.5  # after that (a phone's long hold): within half a second, so a read on
# the web clears the phone's notification right away


@api()
def changes(request):
    import time

    from ..models import ChangeEvent

    last = ChangeEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
    since = int_or_none(request.GET.get("since"))
    if since is None:
        return {"last": last, "events": []}
    wait = min(max(float(int_or_none(request.GET.get("wait")) or 0), 0.0), LONG_POLL)
    if wait and since == last:
        start = time.monotonic()
        deadline = start + wait
        while time.monotonic() < deadline:
            time.sleep(LONG_POLL_TICK if time.monotonic() - start < 20 else LONG_POLL_SLOW_TICK)
            last = ChangeEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
            if last != since:
                break
        if last == since:
            return {"last": last, "events": []}
    if since > last:  # the local copy was reset (restore, new mailbox): reload everything
        return {"last": last, "events": [], "reset": True}
    rows = list(ChangeEvent.objects.filter(id__gt=since).order_by("id").values_list("id", "kind", "data")[:200])
    return {
        "last": rows[-1][0] if rows else since,
        "events": [{"id": i, "kind": k, **(d or {})} for i, k, d in rows],
        "more": len(rows) == 200,
    }


# --- Kern tasks and Home -------------------------------------------------------

@api(("POST",))
def thread_task(request, pk: int):
    """Make a Kern task from this conversation (mail/taskbridge.py)."""
    import datetime as _dt

    from notes import tasks as ntasks

    from .. import taskbridge

    t = Thread.objects.get(pk=pk)
    data = body(request)
    due = None
    if data.get("due"):
        try:
            due = _dt.date.fromisoformat(str(data["due"])[:10])
        except ValueError:
            raise ApiError("Dates look like 2026-11-20.") from None
    try:
        prio = max(0, min(3, int(data.get("priority") or 0)))
    except (TypeError, ValueError):
        prio = 0
    task = taskbridge.task_for_thread(t, title=str(data.get("title") or "").strip()[:500], due=due, priority=prio)
    from .. import events
    events.emit("update", threads=[t.pk])
    return ntasks.task_json(task)


def tasks_for_keys(keys) -> list[dict]:
    from notes import tasks as ntasks
    from notes.models import Task

    keys = [k for k in keys if k]
    if not keys:
        return []
    return [ntasks.task_json(x) for x in Task.objects.filter(source__key__in=keys).order_by("done", "due")[:20]]


@api()
def open_by_key(request):
    """A task's link back to its email: Message-ID -> the conversation now."""
    key = request.GET.get("key", "").strip()[:998]
    tid = Message.objects.filter(message_key=key, thread__isnull=False).exclude(
        folder__role=FolderRole.TRASH).values_list("thread_id", flat=True).first() or \
        Message.objects.filter(message_key=key, thread__isnull=False).values_list("thread_id", flat=True).first()
    if not tid:
        raise ApiError("That email isn't here any more (deleted, or not downloaded yet).", 404, "not_found")
    return {"threadId": tid}


@api()
def today(request):
    """Mail for Kern's Home: what's waiting, coming back and arriving today."""
    from .. import account
    from ..models import Draft, DraftStatus, FollowUp, FollowUpStatus, Snooze, SnoozeStatus

    from ..names import display_name

    if not account.cfg()["USERNAME"]:
        return {"connected": False}
    now = timezone.now()
    end = timezone.localtime(now).replace(hour=23, minute=59, second=59)
    inbox = Folder.objects.filter(role=FolderRole.INBOX).first()
    unread = 0
    if inbox:
        unread = Message.objects.filter(folder=inbox, seen=False).values("thread_id").distinct().count()
    important = []
    if inbox:
        for m in (Message.objects.filter(folder=inbox, seen=False).exclude(risk_level="high")
                  .order_by("-sort_date").select_related("thread")[:5]):
            important.append({"threadId": m.thread_id, "subject": m.subject,
                              "from": display_name({"name": m.from_name, "addr": m.from_addr}),
                              "date": iso(m.sort_date)})
    snoozes = [{"threadId": s.thread_id, "subject": s.subject, "until": iso(s.wake_at)}
               for s in Snooze.objects.filter(status=SnoozeStatus.ACTIVE, wake_at__lte=end).order_by("wake_at")[:10]]
    nudged = [{"threadId": f.thread_id, "subject": f.subject, "id": f.pk}
              for f in FollowUp.objects.filter(status=FollowUpStatus.NUDGED).order_by("due_at")[:10]]
    # Only what really happens today: out for delivery today, ready to collect, or due today.
    # A package whose day has passed without news is not "arriving today" (see _settled).
    ships = []
    today_date = timezone.localdate()
    active, _ = package_buckets(now)
    for p in active:
        at = datetime.fromisoformat(p["statusAt"]) if p["statusAt"] else None
        fresh = at is not None and timezone.localtime(at).date() >= today_date - timedelta(days=0 if p["status"] == "out_for_delivery" else 7)
        if (p["status"] in ("out_for_delivery", "ready_for_pickup") and fresh) or p["expected"] == today_date.isoformat():
            ships.append(p)
    scheduled = Draft.objects.filter(status=DraftStatus.SCHEDULED, send_at__lte=end).count()
    return {"connected": True, "unread": unread, "latest": important, "snoozes": snoozes, "nudged": nudged,
            "packages": ships[:10], "scheduledToday": scheduled}


# --- send mail as (mail/identities.py) --------------------------------------------------

@api(("GET", "POST"))
def identities_view(request):
    from .. import identities

    if request.method == "POST":
        try:
            i = identities.save(body(request))
        except identities.IdentityError as exc:
            raise ApiError(str(exc)) from exc
        return identities.as_json(i)
    return identities.all_json()


@api(("PATCH", "DELETE"))
def identity_detail(request, pk: int):
    from .. import identities

    i = MailIdentity.objects.get(pk=pk)
    if request.method == "DELETE":
        i.delete()
        identities.invalidate()
        return {"ok": True}
    try:
        i = identities.save(body(request), i)
    except identities.IdentityError as exc:
        raise ApiError(str(exc)) from exc
    return identities.as_json(i)


@api(("POST",))
def identity_test(request, pk: int):
    from .. import identities

    i = MailIdentity.objects.get(pk=pk)
    try:
        identities.test(i)
    except identities.IdentityError as exc:
        raise ApiError(str(exc)) from exc
    return {"ok": True}


@api()
def mail_stats(request):
    from .. import stats

    return stats.compute(int_or_none(request.GET.get("days")) or 90)


@api()
def map_tile(request, theme: str, z: int, x: int, y: int):
    """Map tiles for the package map, fetched and cached by the server (mail/geo.py)."""
    from .. import geo

    try:
        data = geo.tile(theme, z, x, y)
    except ValueError as exc:
        raise ApiError(str(exc), 404) from exc
    except OSError as exc:
        raise ApiError("The map isn't available right now.", 502) from exc
    resp = HttpResponse(data, content_type=geo.image_type(data))
    resp["Cache-Control"] = "private, max-age=604800"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
