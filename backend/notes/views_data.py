"""Files, version history, import/export, backups and storage."""
import json
import os
import tempfile

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from . import backup, porting, versions
from .models import Attachment, Block, CardNote, Database, Document, DocVersion
from .views import as_uuid, attachment_json, bad, block_json, get_doc
from .views_db import get_db


def download(data: bytes, filename: str, mime: str, inline=False) -> HttpResponse:
    r = HttpResponse(data, content_type=mime)
    from urllib.parse import quote
    disp = "inline" if inline else "attachment"
    r["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(filename)}"
    return r


# ------------------------------------------------------------------ files


def usage(a: Attachment) -> list[dict]:
    url = a.file.url
    docs = {}
    for b in Block.objects.filter(Q(props__icontains=url) | Q(html__icontains=url)).select_related("document")[:50]:
        docs[b.document_id] = b.document
    for d in Document.objects.filter(cover=url):
        docs[d.id] = d
    out = [{"id": str(d.id), "title": d.title, "trashed": bool(d.trashed_at)} for d in docs.values()]
    cards = CardNote.objects.filter(Q(image=url) | Q(front__icontains=url) | Q(back__icontains=url)).count()
    if cards:
        out.append({"id": None, "title": f"{cards} flashcard{'s' if cards != 1 else ''}", "trashed": False})
    return out


@api_view(["GET"])
def files(request):
    q = request.query_params
    qs = Attachment.objects.all().order_by("-created_at")
    kind = q.get("type")
    if kind in ("image", "video", "audio"):
        qs = qs.filter(mime__startswith=kind + "/")
    elif kind == "pdf":
        qs = qs.filter(mime="application/pdf")
    elif kind == "other":
        qs = qs.exclude(mime__startswith="image/").exclude(mime__startswith="video/").exclude(
            mime__startswith="audio/").exclude(mime="application/pdf")
    if q.get("q"):
        qs = qs.filter(name__icontains=q["q"])
    out = []
    for a in qs[:1000]:
        data = attachment_json(a)
        data["used_in"] = usage(a) if q.get("usage") != "0" else []
        out.append(data)
    return Response(out)


@api_view(["PATCH", "DELETE"])
def file_detail(request, file_id):
    try:
        a = Attachment.objects.get(id=as_uuid(file_id))
    except Attachment.DoesNotExist:
        raise Http404
    if request.method == "DELETE":
        from .views_files import delete_version_files
        path = a.file.path if a.file else None
        delete_version_files(a)
        a.delete()
        if path and os.path.exists(path):
            os.remove(path)
        return Response(status=204)
    name = str(request.data.get("name", "")).strip()[:255]
    if name:
        a.name = name
        a.save(update_fields=["name"])
    return Response(attachment_json(a))


# --------------------------------------------------------------- versions


def version_json(v: DocVersion, full=False) -> dict:
    data = {"id": str(v.id), "created_at": v.created_at, "title": v.title, "icon": v.icon,
            "reason": v.reason, "block_count": v.block_count}
    if full:
        data["blocks"] = v.blocks
    return data


@api_view(["GET", "POST"])
def doc_versions(request, doc_id):
    doc = get_doc(doc_id)
    if request.method == "POST":
        return Response(version_json(versions.snapshot(doc, "manual")), status=201)
    return Response([version_json(v) for v in doc.versions.all()[:500]])


@api_view(["GET"])
def version_detail(request, version_id):
    try:
        v = DocVersion.objects.get(id=as_uuid(version_id))
    except DocVersion.DoesNotExist:
        raise Http404
    return Response(version_json(v, full=True))


@api_view(["POST"])
def version_restore(request, version_id):
    try:
        v = DocVersion.objects.select_related("document").get(id=as_uuid(version_id))
    except DocVersion.DoesNotExist:
        raise Http404
    with transaction.atomic():
        versions.restore(v.document, v)
    return Response({"ok": True, "blocks": [block_json(b) for b in v.document.blocks.all()]})


# ----------------------------------------------------------------- export


@api_view(["GET"])
def export_document(request, doc_id):
    doc = get_doc(doc_id, include_trashed=False)
    fmt = request.query_params.get("as", "md")
    children = request.query_params.get("children") == "1"
    if fmt == "json":
        data = json.dumps(porting.export_kern_json([doc.id] if children else [doc.id]), ensure_ascii=False, indent=1)
        return download(data.encode(), f"{porting.safe_name(doc.title)}.json", "application/json")
    if fmt == "opml":
        return download(porting.export_opml(doc), f"{porting.safe_name(doc.title)}.opml", "text/x-opml")
    if fmt in ("print", "pdf"):
        return HttpResponse(porting.Exporter().html(doc, print_mode=True), content_type="text/html")
    if fmt not in ("md", "html"):
        return bad("Unknown format.")
    data, name, mime = porting.export_tree(doc, fmt, include_children=children)
    return download(data, name, mime)


@api_view(["GET"])
def export_database(request, db_id):
    db = get_db(db_id)
    fmt = request.query_params.get("as", "csv")
    if fmt == "json":
        data = json.dumps(porting.export_kern_json([db.page_id]), ensure_ascii=False, indent=1)
        return download(data.encode(), f"{porting.safe_name(db.page.title)}.json", "application/json")
    data, name, mime = porting.export_database_csv(db)
    return download(data, name, mime)


@api_view(["GET"])
def export_cards(request):
    qs = CardNote.objects.filter(active=True).select_related("deck", "document")
    deck = request.query_params.get("deck")
    if deck == "none":
        qs = qs.filter(deck__isnull=True)
    elif deck:
        qs = qs.filter(deck_id=as_uuid(deck))
    qs = qs.filter(Q(document__isnull=True) | Q(document__trashed_at__isnull=True))
    if request.query_params.get("as") == "apkg":
        data, name, mime = porting.export_anki(list(qs))
    else:
        data, name, mime = porting.export_cards_csv(qs)
    return download(data, name, mime)


@api_view(["GET"])
def export_workspace(request):
    fmt = request.query_params.get("as", "md")
    if fmt == "json":
        roots = list(Document.objects.filter(parent__isnull=True, entry_of__isnull=True, trashed_at__isnull=True,
                                             is_template=False).values_list("id", flat=True))
        data = json.dumps(porting.export_kern_json(roots), ensure_ascii=False, indent=1)
        return download(data.encode(), "Kern workspace.json", "application/json")
    data, name, mime = porting.export_tree(None, "html" if fmt == "html" else "md")
    if mime != "application/zip":  # a single page: still give a zip for "the whole workspace"
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name, data)
        data, name = buf.getvalue(), "Kern workspace.zip"
    return download(data, name, "application/zip")


# ----------------------------------------------------------------- import


@api_view(["POST"])
@parser_classes([MultiPartParser])
def import_view(request):
    uploads = request.FILES.getlist("files")
    paths = request.POST.getlist("paths")
    if not uploads:
        return bad("Choose at least one file.")
    parent = get_doc(request.POST["parent"], include_trashed=False) if request.POST.get("parent") else None
    entries = []
    for i, f in enumerate(uploads):
        name = paths[i] if i < len(paths) and paths[i] else f.name
        entries.append((name, f.read()))
    try:
        with transaction.atomic():
            summary = porting.import_files(entries, parent)
    except (ValueError, KeyError) as e:
        return bad(str(e))
    return Response(summary, status=201)


# ---------------------------------------------------------------- backups


@api_view(["GET", "POST"])
def backups(request):
    if request.method == "POST":
        return Response(backup.create("manual"), status=201)
    return Response(backup.list_backups())


@api_view(["GET", "DELETE"])
def backup_detail(request, name):
    try:
        path = backup.path_for(name)
    except FileNotFoundError:
        raise Http404
    if request.method == "DELETE":
        os.remove(path)
        return Response(status=204)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


@api_view(["POST"])
def backup_restore(request, name):
    try:
        path = backup.path_for(name)
    except FileNotFoundError:
        raise Http404
    try:
        return Response(backup.restore(path))
    except (ValueError, OSError) as e:
        return bad(str(e))


@api_view(["POST"])
@parser_classes([MultiPartParser])
def backup_upload_restore(request):
    f = request.FILES.get("file")
    if not f:
        return bad("Choose a backup file.")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=settings.DATA_DIR)
    try:
        for chunk in f.chunks():
            tmp.write(chunk)
        tmp.close()
        return Response(backup.restore(tmp.name))
    except (ValueError, OSError, KeyError) as e:
        return bad(str(e))
    except Exception as e:  # zipfile.BadZipFile and friends
        return bad(f"Could not read this backup: {e}")
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


@api_view(["GET"])
def storage(request):
    return Response(backup.storage())


@api_view(["POST"])
def clear_recent(request):
    Document.objects.update(last_opened_at=None)
    return Response({"ok": True})


# --------------------------------------------------------------------- AI

from . import ai as ai_mod  # noqa: E402


def _ai_error(e):
    return Response({"detail": str(e), "setup": e.status == 409}, status=e.status)


@api_view(["GET", "PUT"])
def ai_config(request):
    if request.method == "PUT":
        try:
            return Response(ai_mod.save_config(request.data))
        except ai_mod.AIError as e:
            return _ai_error(e)
    return Response(ai_mod.public_config())


@api_view(["POST"])
def ai_test(request):
    try:
        text = ai_mod.complete("You are a connection test. Reply with exactly: OK", "Reply with OK.")
    except ai_mod.AIError as e:
        return _ai_error(e)
    return Response({"ok": True, "reply": text[:200]})


def _doc_from(request):
    doc_id = request.data.get("doc")
    return get_doc(doc_id, include_trashed=False) if doc_id else None


@api_view(["POST"])
def ai_write(request):
    prompt = str(request.data.get("prompt", "")).strip()
    if not prompt:
        return bad("Tell the assistant what to write.")
    doc = _doc_from(request)
    context, truncated = ai_mod.page_context(doc)
    selection = str(request.data.get("selection", "")).strip()
    parts = []
    if context:
        parts.append(f"<page>\n{context}\n</page>")
    if selection:
        parts.append(f"<current_block>\n{selection}\n</current_block>")
    parts.append(f"Request: {prompt}")
    try:
        text = ai_mod.complete(ai_mod.WRITE_SYSTEM, "\n\n".join(parts))
    except ai_mod.AIError as e:
        return _ai_error(e)
    return Response({"markdown": text, "truncated": truncated})


@api_view(["POST"])
def ai_cards(request):
    prompt = str(request.data.get("prompt", "")).strip()
    doc = _doc_from(request)
    if not prompt and not doc:
        return bad("Give a topic, paste some text, or choose a page.")
    try:
        count = max(1, min(50, int(request.data.get("count") or 10)))
    except (TypeError, ValueError):
        count = 10
    context, truncated = ai_mod.page_context(doc)
    parts = [f"<source>\n{context}\n</source>"] if context else []
    if prompt:
        parts.append(f"<request>\n{prompt}\n</request>")
    parts.append(f"Write about {count} flashcards.")
    try:
        data = ai_mod.parse_json(ai_mod.complete(ai_mod.CARDS_SYSTEM, "\n\n".join(parts)))
    except ai_mod.AIError as e:
        return _ai_error(e)
    if isinstance(data, dict):
        data = data.get("cards") or []
    cards = []
    for c in data if isinstance(data, list) else []:
        if not isinstance(c, dict):
            continue
        kind = c.get("kind") if c.get("kind") in ("basic", "cloze", "concept") else "basic"
        front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
        if not front or (kind != "cloze" and not back) or (kind == "cloze" and "{{" not in front):
            continue
        cards.append({"kind": kind, "front": front[:2000], "back": back[:4000]})
    if not cards:
        return bad("The assistant did not return any usable cards. Try rephrasing.")
    return Response({"cards": cards, "truncated": truncated})


@api_view(["POST"])
def ai_template(request):
    prompt = str(request.data.get("prompt", "")).strip()
    if not prompt:
        return bad("Describe the template you want.")
    try:
        data = ai_mod.parse_json(ai_mod.complete(ai_mod.TEMPLATE_SYSTEM, prompt))
    except ai_mod.AIError as e:
        return _ai_error(e)
    if not isinstance(data, dict) or not str(data.get("markdown", "")).strip():
        return bad("The assistant did not return a usable template. Try rephrasing.")
    from .views_db import template_json
    with transaction.atomic():
        t = Document.objects.create(is_template=True, title=str(data.get("title") or "New template")[:500],
                                    icon=str(data.get("icon") or "")[:8])
        blocks = porting.insert_trees(t, porting.markdown_to_trees(str(data["markdown"]), porting.Ctx()))
        porting.finish_doc(t, blocks)
    return Response(template_json(t), status=201)


# ------------------------------------------------------------- Intelligence

from . import agent  # noqa: E402
from .models import Chat  # noqa: E402


def chat_json(c: Chat, full=False) -> dict:
    out = {"id": str(c.id), "title": c.title or "New chat", "updated_at": c.updated_at.isoformat(),
           "created_at": c.created_at.isoformat()}
    if full:
        out["messages"] = c.transcript
    return out


@api_view(["GET", "POST"])
def chats(request):
    if request.method == "POST":
        c = Chat.objects.create(title=str(request.data.get("title") or "")[:200])
        return Response(chat_json(c, True), status=201)
    return Response([chat_json(c) for c in Chat.objects.all()[:200]])


def _get_chat(chat_id) -> Chat:
    c = Chat.objects.filter(id=as_uuid(chat_id)).first()
    if not c:
        raise Http404
    return c


@api_view(["GET", "PATCH", "DELETE"])
def chat_detail(request, chat_id):
    c = _get_chat(chat_id)
    if request.method == "DELETE":
        c.delete()
        return Response(status=204)
    if request.method == "PATCH":
        c.title = str(request.data.get("title") or "")[:200]
        c.save(update_fields=["title"])
    return Response(chat_json(c, True))


@api_view(["POST"])
def chat_message(request, chat_id):
    c = _get_chat(chat_id)
    text = str(request.data.get("text") or "").strip()
    if not text:
        return bad("Write a message first.")
    try:
        agent.chat_turn(c, text[:20000], request.data.get("page"))
    except ai_mod.AIError as e:
        return _ai_error(e)
    return Response(chat_json(c, True))
