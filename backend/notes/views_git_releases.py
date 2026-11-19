"""JSON API for git releases (under /api/git/repos/<name>/releases) and the asset download."""
import re
from urllib.parse import quote

from django.db.models import F
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from . import git_releases as gr
from . import gitrepo as g
from .models_git_releases import Release, ReleaseAsset
from .views import bad
from .views_git import handle, _plain


def _release(repo, rid) -> Release:
    g.repo_path(repo)
    return get_object_or_404(Release, pk=rid, repo=repo)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


@api_view(["GET", "POST"])
@handle
def releases(request, name):
    g.repo_path(name)
    if request.method == "POST":
        d = _body(request)
        r = gr.create_release(name, d.get("tag"), target=d.get("target"), title=d.get("title", ""),
                              notes=d.get("notes", ""), draft=d.get("draft", False),
                              prerelease=d.get("prerelease", False))
        return Response(gr.release_json(r, gr.tag_names(name)), status=201)
    tags = gr.tag_names(name)
    return Response([gr.release_json(r, tags) for r in gr.releases_for(name).prefetch_related("assets")])


@api_view(["GET"])
@handle
def release_latest(request, name):
    g.repo_path(name)
    r = gr.latest(name)
    if r is None:
        return bad("No releases yet.", 404)
    return Response(gr.release_json(r, gr.tag_names(name)))


@api_view(["GET", "PATCH", "DELETE"])
@handle
def release_detail(request, name, rid):
    r = _release(name, rid)
    if request.method == "DELETE":
        flag = request.query_params.get("delete_tag") or _body(request).get("delete_tag")
        gr.delete_release(r, str(flag).lower() in ("1", "true", "yes"))
        return Response(status=204)
    if request.method == "PATCH":
        gr.update_release(r, _body(request))
    return Response(gr.release_json(r, gr.tag_names(name)))


@api_view(["POST"])
@parser_classes([MultiPartParser])
@handle
def release_assets(request, name, rid):
    r = _release(name, rid)
    uploads = request.FILES.getlist("files") + request.FILES.getlist("file")
    if not uploads:
        return bad("Choose at least one file.")
    limit = gr.max_file_size()
    if any(f.size > limit for f in uploads):
        return bad(f"A file may be at most {limit} bytes.", 413)
    for f in uploads:
        gr.store_file(r, f.name, f.chunks(), limit=limit)
    return Response(gr.release_json(r, gr.tag_names(name)), status=201)


@api_view(["DELETE"])
@handle
def release_asset(request, name, rid, aid):
    r = _release(name, rid)
    gr.delete_asset(get_object_or_404(ReleaseAsset, pk=aid, release=r))
    return Response(gr.release_json(r, gr.tag_names(name)))


def _range(header: str, size: int):
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    else:
        n = int(m.group(2))
        start, end = max(0, size - n), size - 1
    return (start, end) if start <= end and start < size else False


def _chunks(path, start, end):
    left = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while left > 0:
            data = f.read(min(1024 * 1024, left))
            if not data:
                break
            left -= len(data)
            yield data


def asset_download(request, name, rid, aid):
    try:
        if request.method not in ("GET", "HEAD"):
            return HttpResponse(status=405)
        r = _release(name, rid)
        a = get_object_or_404(ReleaseAsset, pk=aid, release=r)
        path = gr.asset_path(a)
        if not path.is_file():
            return _plain("The file is missing.", 404)
        size = path.stat().st_size
        rng = _range(request.headers.get("Range"), size) if request.headers.get("Range") else None
        if rng is False:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        if rng is None:
            resp = FileResponse(open(path, "rb"), content_type=a.content_type or "application/octet-stream")
            resp["Content-Length"] = size
        else:
            resp = StreamingHttpResponse(_chunks(path, *rng), status=206,
                                         content_type=a.content_type or "application/octet-stream")
            resp["Content-Range"] = f"bytes {rng[0]}-{rng[1]}/{size}"
            resp["Content-Length"] = rng[1] - rng[0] + 1
        if request.method == "GET" and (rng is None or rng[0] == 0):
            ReleaseAsset.objects.filter(pk=a.pk).update(downloads=F("downloads") + 1)
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(a.filename)}"
        resp["Content-Security-Policy"] = "default-src 'none'; sandbox"
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Accept-Ranges"] = "bytes"
        return resp
    except g.GitError as e:
        return _plain(str(e), e.status)
