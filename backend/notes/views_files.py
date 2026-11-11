"""Editing files in place (with recoverable versions), PDF annotations and range-aware media serving."""
import mimetypes
import os
import posixpath
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from kern import tenancy
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.utils import timezone
from django.utils._os import safe_join
from django.utils.http import http_date, parse_http_date_safe
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Attachment, AttachmentVersion, FileAnnotation
from .views import as_uuid, attachment_json, bad

MAX_EDIT_BYTES = 20 * 1024 * 1024
KEEP_VERSIONS = 50
KINDS = ("highlight", "note")
COLORS = {"yellow", "green", "blue", "pink", "orange", "purple"}


def get_attachment(file_id) -> Attachment:
    a = Attachment.objects.filter(id=as_uuid(file_id)).first()
    if not a or not a.file:
        raise Http404
    return a


def marker(a: Attachment) -> str:
    """Identifies the current content; the editor sends it back so it cannot overwrite a newer save."""
    return (a.updated_at or a.created_at).isoformat()


def file_json(a: Attachment) -> dict:
    data = attachment_json(a)
    data["updated_at"] = a.updated_at
    data["base"] = marker(a)
    data["versions"] = a.versions.count()
    return data


def version_json(v: AttachmentVersion) -> dict:
    return {"id": str(v.id), "url": v.file.url, "size": v.size, "reason": v.reason, "created_at": v.created_at}


def _ext(a: Attachment) -> str:
    name = os.path.basename(a.file.name)
    return name.rsplit(".", 1)[-1] if "." in name else "bin"


def _snapshot(a: Attachment, reason: str) -> AttachmentVersion:
    v = AttachmentVersion(attachment=a, size=a.size, reason=reason)
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S-%f")
    with open(a.file.path, "rb") as fh:
        v.file.save(f"{a.id}-{stamp}.{_ext(a)}", File(fh), save=True)
    return v


def _prune(a: Attachment):
    for old in a.versions.all()[KEEP_VERSIONS:]:
        path = old.file.path if old.file else None
        old.delete()
        if path and os.path.exists(path):
            os.remove(path)


def _write(a: Attachment, chunks):
    """Replace the file's bytes at the same path (pages link to its URL), atomically."""
    target = a.file.path
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".edit-")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in chunks:
                size += len(chunk)
                out.write(chunk)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    a.size = size
    a.updated_at = timezone.now()
    a.save(update_fields=["size", "updated_at"])


@api_view(["GET", "PUT"])
@parser_classes([JSONParser, MultiPartParser])
def file_content(request, file_id):
    """GET: metadata for the editor. PUT: replace the content, keeping the old one as a version.

    Body: JSON {"content": "...", "base": "<marker>"} for text, or multipart "file" (+ "base").
    """
    a = get_attachment(file_id)
    if request.method == "GET":
        return Response(file_json(a))
    base = request.data.get("base")
    if base and str(base) != marker(a):
        return Response({"detail": "This file was changed somewhere else since you opened it. Reload it, then make your edit again.",
                         "conflict": True, "base": marker(a)}, status=409)
    upload = request.FILES.get("file")
    if upload is not None:
        if upload.size > MAX_EDIT_BYTES * 10:
            return bad("That file is too large to replace here.")
        chunks = upload.chunks()
    else:
        content = request.data.get("content")
        if not isinstance(content, str):
            return bad("Send the new text as “content”.")
        data = content.encode("utf-8")
        if len(data) > MAX_EDIT_BYTES:
            return bad("That text is too large to save (20 MB at most).")
        chunks = [data]
    if not os.path.exists(a.file.path):
        raise Http404
    with tenancy.atomic():
        _snapshot(a, "edit")
        _write(a, chunks)
        _prune(a)
    return Response(file_json(a))


@api_view(["GET"])
def file_versions(request, file_id):
    a = get_attachment(file_id)
    return Response({"current": file_json(a), "versions": [version_json(v) for v in a.versions.all()]})


@api_view(["POST"])
def file_version_restore(request, file_id, version_id):
    a = get_attachment(file_id)
    v = a.versions.filter(id=as_uuid(version_id)).first()
    if not v or not v.file or not os.path.exists(v.file.path):
        raise Http404
    with tenancy.atomic():
        _snapshot(a, "restore")  # so the restore itself can be undone
        with open(v.file.path, "rb") as fh:
            _write(a, iter(lambda: fh.read(1 << 20), b""))
        _prune(a)
    return Response(file_json(a))


def delete_version_files(a: Attachment):
    """Called before an attachment is deleted: the rows cascade, the files on disk do not."""
    for v in a.versions.all():
        if v.file and os.path.exists(v.file.path):
            os.remove(v.file.path)


# ------------------------------------------------------------ annotations


def annotation_json(n: FileAnnotation) -> dict:
    return {"id": str(n.id), "page": n.page, "kind": n.kind, "color": n.color, "rects": n.rects,
            "text": n.text, "note": n.note, "created_at": n.created_at, "updated_at": n.updated_at}


def _clean_rects(value):
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("rects must be a list of [x, y, w, h].")
    out = []
    for r in value:
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            raise ValueError("rects must be a list of [x, y, w, h].")
        try:
            x, y, w, h = (round(min(1.0, max(0.0, float(n))), 5) for n in r)
        except (TypeError, ValueError):
            raise ValueError("rects must be numbers.")
        out.append([x, y, w, h])
    return out


def _apply(n: FileAnnotation, data, creating=False):
    if creating or "page" in data:
        try:
            n.page = max(1, int(data.get("page")))
        except (TypeError, ValueError):
            raise ValueError("page must be a page number.")
    if creating or "kind" in data:
        kind = data.get("kind", "highlight")
        if kind not in KINDS:
            raise ValueError("kind must be highlight or note.")
        n.kind = kind
    if "color" in data:
        n.color = data["color"] if data["color"] in COLORS else "yellow"
    if creating or "rects" in data:
        n.rects = _clean_rects(data.get("rects", []))
        if not n.rects:
            raise ValueError("An annotation needs a position.")
    if "text" in data:
        n.text = str(data["text"] or "")[:20000]
    if "note" in data:
        n.note = str(data["note"] or "")[:20000]


@api_view(["GET", "POST"])
def file_annotations(request, file_id):
    a = get_attachment(file_id)
    if request.method == "POST":
        n = FileAnnotation(attachment=a)
        try:
            _apply(n, request.data, creating=True)
        except ValueError as e:
            return bad(str(e))
        n.save()
        return Response(annotation_json(n), status=201)
    return Response([annotation_json(n) for n in a.annotations.all()])


@api_view(["PATCH", "DELETE"])
def file_annotation_detail(request, file_id, annotation_id):
    a = get_attachment(file_id)
    n = a.annotations.filter(id=as_uuid(annotation_id)).first()
    if not n:
        raise Http404
    if request.method == "DELETE":
        n.delete()
        return Response(status=204)
    try:
        _apply(n, request.data)
    except ValueError as e:
        return bad(str(e))
    n.save()
    return Response(annotation_json(n))


# ------------------------------------------------------------------ media

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _ranged(fh, start: int, length: int, block=1 << 16):
    fh.seek(start)
    try:
        while length > 0:
            chunk = fh.read(min(block, length))
            if not chunk:
                break
            length -= len(chunk)
            yield chunk
    finally:
        fh.close()


def serve_media(request, path):
    """Development / fallback media server with HTTP range support, so audio and video can seek
    and stream instead of downloading whole. (In Docker, Caddy serves /media and does the same.)"""
    path = posixpath.normpath(path).lstrip("/")
    try:
        full = Path(safe_join(tenancy.media_root(), path))
    except Exception:
        raise Http404
    if not full.is_file():
        raise Http404
    stat = full.stat()
    mtime = int(stat.st_mtime)
    since = parse_http_date_safe(request.headers.get("If-Modified-Since", ""))
    if since is not None and since >= mtime and "Range" not in request.headers:
        return HttpResponseNotModified()
    mime, encoding = mimetypes.guess_type(str(full))
    mime = mime or "application/octet-stream"
    size = stat.st_size
    m = RANGE_RE.match(request.headers.get("Range", "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:  # suffix range: the last N bytes
            start = max(0, size - int(m.group(2)))
            end = size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            r = HttpResponse(status=416)
            r["Content-Range"] = f"bytes */{size}"
            return r
        length = end - start + 1
        r = StreamingHttpResponse(_ranged(open(full, "rb"), start, length), status=206, content_type=mime)
        r["Content-Range"] = f"bytes {start}-{end}/{size}"
        r["Content-Length"] = str(length)
    else:
        r = FileResponse(open(full, "rb"), content_type=mime)
        r["Content-Length"] = str(size)
    if encoding:
        r["Content-Encoding"] = encoding
    r["Accept-Ranges"] = "bytes"
    r["Last-Modified"] = http_date(stat.st_mtime)
    # Text files can now be edited in place under the same URL, so revalidate instead of caching forever.
    r["Cache-Control"] = "private, no-cache"
    return r
