"""JSON API for the Svelte frontend. Every view here requires a logged-in
session (enforced by accounts.middleware.ApiLoginRequiredMiddleware)."""

from __future__ import annotations

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
from .. import actions, followups, imgproxy, labels as labels_mod, parsing, risk, sanitize, search, sending, snooze, spam, store
from ..identity import my_addresses
from ..models import (
    Attachment, BlockRule, Correspondent, Draft, DraftStatus, Folder, FolderRole, Label, Message,
    OpStatus, OutboxOp, Thread, TrustedImageSender, Upload, WorkerStatus,
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
                fups: dict | None = None, muted: set | None = None, pkgs: dict | None = None) -> dict:
    s = (snoozes or {}).get(t.id)
    f = (fups or {}).get(t.id)
    return {
        "id": t.id,
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
             "inline": a.inline, "previewable": _previewable(a.content_type)}
            for a in m.attachments.all()
        ],
        "risk": {"level": m.risk_level, "score": m.risk_score, "findings": m.risk_findings},
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


def _previewable(ctype: str) -> bool:
    return ctype.lower() in INLINE_SAFE


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
    unread = dict(
        Message.objects.filter(seen=False, thread__isnull=False).values("folder_id")
        .annotate(n=Count("thread_id", distinct=True)).values_list("folder_id", "n")
    )
    totals = dict(
        Message.objects.filter(thread__isnull=False).values("folder_id")
        .annotate(n=Count("thread_id", distinct=True)).values_list("folder_id", "n")
    )
    fs = sorted(Folder.objects.filter(selectable=True), key=lambda f: (ROLE_ORDER.get(f.role, 7), f.name.lower()))
    starred = Thread.objects.filter(starred=True).count()
    return {
        "folders": [folder_json(f, unread.get(f.id, 0), totals.get(f.id, 0)) for f in fs],
        "labels": [label_json(lb) for lb in Label.objects.all()],
        "starred": starred,
    }


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


@api()
def threads(request):
    view = request.GET.get("view", "")
    q = request.GET.get("q", "").strip()[:500]
    qs = _thread_queryset(view, q)
    if request.GET.get("unread") == "1":
        unread = Message.objects.filter(thread=OuterRef("pk"), seen=False)
        if view.startswith("folder:"):
            unread = unread.filter(folder_id=int_or_none(view.split(":", 1)[1]))
        qs = qs.filter(Exists(unread))
    qs = qs.order_by("-last_date", "-id")
    cursor = request.GET.get("cursor")
    if cursor:
        try:
            ts, tid = cursor.rsplit("|", 1)
            dt = datetime.fromisoformat(ts)
            qs = qs.filter(Q(last_date__lt=dt) | Q(last_date=dt, id__lt=int(tid)))
        except ValueError:
            raise ApiError("Bad cursor.") from None
    page = list(qs[: PAGE + 1])
    more = len(page) > PAGE
    page = page[:PAGE]
    folders_by_thread: dict[int, list[int]] = {}
    for tid, fid in Message.objects.filter(thread_id__in=[t.id for t in page]).values_list("thread_id", "folder_id").distinct():
        folders_by_thread.setdefault(tid, []).append(fid)
    next_cursor = f"{page[-1].last_date.isoformat()}|{page[-1].id}" if more and page[-1].last_date else None
    ids = [t.id for t in page]
    snoozes = snooze.active_for_threads(ids)
    fups = followups.open_for_threads(ids)
    muted = mute_mod.muted_thread_ids(ids)
    pkgs = _package_chips(ids)
    return {"threads": [thread_json(t, folders_by_thread, snoozes, fups, muted, pkgs) for t in page], "next": next_cursor}


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


@api(("POST",))
def thread_actions(request):
    data = body(request)
    action = data.get("action")
    if action not in THREAD_ACTIONS:
        raise ApiError("Unknown action.")
    ids = [int(i) for i in data.get("ids", [])][:500]
    context = Folder.objects.filter(pk=int_or_none(data.get("context"))).first() if data.get("context") else None
    result: dict = {"ok": True}
    for t in Thread.objects.filter(pk__in=ids):
        msgs = list(Message.objects.filter(thread=t).select_related("folder"))
        if action in ("read", "unread"):
            target = [m for m in msgs if m.seen != (action == "read")]
            actions.set_flags(target, **({"add": ["\\Seen"]} if action == "read" else {"remove": ["\\Seen"]}))
        elif action == "star":
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


@api()
def message_body(request, pk: int):
    m = _message(pk)
    raw = store.get(m.blob_id)
    pm = parsing.parse_message(raw)
    trusted = TrustedImageSender.objects.filter(address=m.from_addr).exists()
    load = request.GET.get("images") == "1" or trusted
    # Never auto-load images for risky mail, even from a "trusted" sender.
    if m.risk_level == "high" and request.GET.get("images") != "1":
        load = False
    cid_map = {a.content_id: a.id for a in m.attachments.all() if a.content_id}
    if pm.html:
        res = sanitize.sanitize_html(pm.html, message_pk=m.pk, load_images=load, cid_map=cid_map)
        html, remote = res.html, res.remote_images
    else:
        html, remote = None, 0
    return {
        "html": html,
        "text": pm.text if not pm.html else None,
        "textHtml": sanitize.linkify_text(pm.text) if not pm.html else None,
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


@api()
def attachment(request, pk: int, aid: int):
    m = _message(pk)
    att = Attachment.objects.get(pk=aid, message=m)
    part = parsing.find_part(store.get(m.blob_id), att.part_index)
    if part is None:
        raise ApiError("Attachment not found.", 404, "not_found")
    data = part.payload()
    inline = request.GET.get("inline") == "1" and _previewable(att.content_type)
    # SECURITY: anything not a known-safe raster image is served as a download
    # with a generic type, so the browser never renders attacker content
    # (HTML, SVG, PDF) on our origin.
    ctype = att.content_type.lower() if inline else "application/octet-stream"
    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = content_disposition_header(not inline, att.filename)
    resp["Content-Security-Policy"] = "sandbox; default-src 'none'"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


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
    if data.get("action") == "done":
        f.status = FollowUpStatus.DONE
    elif data.get("action") == "later":
        try:
            until = datetime.fromisoformat(str(data.get("until", "")))
        except ValueError:
            raise ApiError("Pick a time.") from None
        if timezone.is_naive(until) or until <= timezone.now():
            raise ApiError("Pick a time in the future.")
        f.status, f.due_at = FollowUpStatus.WAITING, until
    else:
        raise ApiError("Unknown action.")
    f.save()
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
    for tid, key in sorted(rows, key=lambda r: by_key[r[1]].status_at):
        s = by_key[key]
        out[tid] = {"status": s.status, "label": pk.STATUS_LABEL.get(s.status, s.status)}
    for s in ships:  # thread set directly (e.g. after a resync changed keys)
        if s.thread_id in thread_ids and s.thread_id not in out:
            out[s.thread_id] = {"status": s.status, "label": pk.STATUS_LABEL.get(s.status, s.status)}
    return out


def shipment_json(s) -> dict:
    from .. import packages

    tid = s.thread_id
    if not tid and s.message_keys:
        tid = Message.objects.filter(message_key__in=s.message_keys, thread__isnull=False).values_list("thread_id", flat=True).first()
    carrier = packages.CARRIERS.get(s.carrier)
    return {
        "id": s.id, "number": s.number, "carrier": s.carrier, "carrierName": carrier.name if carrier else s.carrier,
        "status": s.status, "statusLabel": packages.STATUS_LABEL.get(s.status, s.status), "statusAt": iso(s.status_at),
        "step": packages.STATUS_STEP.get(s.status, 1),
        "expected": s.expected.isoformat() if s.expected else None, "expectedText": s.expected_text,
        "merchant": s.merchant, "subject": s.subject, "trackUrl": packages.track_url(s.carrier, s.number),
        "threadId": tid, "hidden": s.hidden,
    }


@api()
def packages_list(request):
    from ..models import Shipment

    now = timezone.now()
    recent = now - timedelta(days=14)
    qs = Shipment.objects.filter(hidden=False)
    # No news for 30 days and not expected any more: it almost certainly
    # arrived (or the shop stopped emailing). Drop it rather than nag.
    stale = Q(status_at__lt=now - timedelta(days=30)) & (Q(expected__isnull=True) | Q(expected__lt=(now - timedelta(days=7)).date()))
    active = [shipment_json(s) for s in qs.exclude(status="delivered").exclude(stale).order_by("expected", "-status_at")[:100]]
    done = [shipment_json(s) for s in qs.filter(status="delivered", status_at__gte=recent).order_by("-status_at")[:50]]
    return {"active": active, "delivered": done}


@api(("POST",))
def package_action(request, pk: int):
    from ..models import Shipment

    s = Shipment.objects.get(pk=pk)
    action = body(request).get("action")
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
    "archive": (Q(content_type__icontains="zip") | Q(content_type__icontains="compressed")
                | Q(content_type__icontains="tar") | Q(content_type__icontains="7z")),
}


def _file_kind(a) -> str:
    ct, fn = a.content_type.lower(), a.filename.lower()
    if ct.startswith("image/"):
        return "image"
    if ct == "application/pdf" or fn.endswith(".pdf"):
        return "pdf"
    if any(w in ct for w in ("zip", "compressed", "tar", "7z")):
        return "archive"
    if any(w in ct for w in ("word", "spreadsheet", "presentation", "opendocument", "excel", "powerpoint")) or ct in ("text/csv", "text/plain"):
        return "doc"
    return "other"


@api()
def attachments_list(request):
    """Every real (non-inline) attachment, newest first. Trash and Junk are
    left out. ?kind=image|pdf|doc|archive|other  ?q=filename or sender  ?before=<id>"""
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
# polls this cheap endpoint every few seconds.

@api()
def changes(request):
    from ..models import ChangeEvent

    last = ChangeEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
    since = int_or_none(request.GET.get("since"))
    if since is None:
        return {"last": last, "events": []}
    if since > last:  # the local copy was reset (restore, new mailbox): reload everything
        return {"last": last, "events": [], "reset": True}
    rows = list(ChangeEvent.objects.filter(id__gt=since).order_by("id").values_list("id", "kind", "data")[:200])
    return {
        "last": rows[-1][0] if rows else since,
        "events": [{"id": i, "kind": k, **(d or {})} for i, k, d in rows],
        "more": len(rows) == 200,
    }
