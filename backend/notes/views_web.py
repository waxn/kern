"""API views for the web archive (bookmarks, saved pages, downloaded videos)."""

import html as htmllib
import ipaddress
import re
import shutil
import socket
import threading
import time
from urllib.parse import urljoin, urlparse

import nh3
import requests
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models_web import WebArchive
from .views import bad

VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "tiktok.com", "dailymotion.com")
IMAGE_RE = re.compile(r"\.(jpe?g|png|gif|webp|bmp|svg|avif)$", re.I)
MAX_HTML = 5_000_000
USER_AGENT = "Mozilla/5.0 (compatible; KernArchive/1.0)"
QUALITY_HEIGHT = {"1080p": 1080, "720p": 720, "480p": 480}


# ------------------------------------------------------------------ utils


def detect_kind(url: str) -> str:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        return "video"
    if IMAGE_RE.search(p.path):
        return "image"
    return "web"


def check_url(url: str):
    """Return an error string if the URL must not be fetched server-side, else None.

    Blocks non-http(s) schemes and hosts resolving to private/loopback/link-local addresses.
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "Only http(s) URLs can be archived."
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        return "Could not resolve that host."
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "That address is not allowed."
    return None


def meta_content(page: str, *names: str) -> str:
    for name in names:
        for pat in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']',
        ):
            m = re.search(pat, page, re.I)
            if m and m.group(1).strip():
                return htmllib.unescape(m.group(1).strip())
    return ""


def page_title(page: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return htmllib.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def video_dir(archive) -> str:
    return str(settings.MEDIA_ROOT / "web" / str(archive.id))


def video_url(archive):
    return settings.MEDIA_URL + archive.video_path if archive.video_path else ""


def summary(a: WebArchive) -> dict:
    return {
        "id": str(a.id),
        "url": a.url,
        "title": a.title,
        "kind": a.kind,
        "thumbnail": a.thumbnail,
        "duration": a.duration,
        "author": a.author,
        "description": a.description[:300],
        "notes_count": 1 if a.notes.strip() else 0,
        "todo_count": len(a.todos or []),
        "is_processed": a.is_processed,
        "error_message": a.error_message,
        "video_status": a.video_status,
        "video_progress": a.video_progress if a.video_status == "downloading" else None,
        "video_url": video_url(a),
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


def detail(a: WebArchive) -> dict:
    d = summary(a)
    d.update(
        description=a.description,
        has_html=bool(a.html_content),
        has_snapshot=a.html_content.startswith("<!-- kern:snapshot"),
        download_video=a.download_video,
        video_format=a.video_format,
        video_quality=a.video_quality,
        notes=a.notes,
        todos=a.todos or [],
        last_viewed_at=a.last_viewed_at.isoformat() if a.last_viewed_at else None,
    )
    return d


def get_archive(archive_id) -> WebArchive:
    try:
        return WebArchive.objects.get(id=int(archive_id))
    except (WebArchive.DoesNotExist, ValueError):
        raise Http404


def clean_todos(value):
    """Todos are stored as [{"text": str, "done": bool}]; plain strings are accepted."""
    out = []
    for t in value if isinstance(value, list) else []:
        if isinstance(t, dict):
            text, done = str(t.get("text", "")).strip(), bool(t.get("done"))
        else:
            text, done = str(t).strip(), False
        if text:
            out.append({"text": text[:500], "done": done})
    return out


def fetch_page(url: str):
    """GET a page following redirects manually so every hop passes check_url."""
    for _ in range(5):
        err = check_url(url)
        if err:
            raise ValueError(err)
        r = requests.get(
            url, timeout=20, stream=True, allow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
        )
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        r.raise_for_status()
        raw = r.raw.read(MAX_HTML, decode_content=True)
        r.close()
        # The header's charset, else the page's own <meta charset>, else UTF-8 (requests would
        # guess ISO-8859-1 for text/html without a charset, garbling most pages).
        from .snapshot import decode_html
        return url, r.headers.get("content-type", ""), decode_html(raw, r.headers.get("content-type", ""))
    raise ValueError("Too many redirects.")


def process(a: WebArchive):
    """Fetch the page, store sanitised HTML and fill in missing metadata."""
    a.error_message = None
    # What was already set (by the user, or an earlier fetch) is kept; this run only fills gaps.
    had = {"title": a.title, "author": a.author, "description": a.description, "thumbnail": a.thumbnail}
    try:
        final, ctype, body = fetch_page(a.url)
        if a.kind == "image" or ctype.startswith("image/"):
            a.kind = "image"
            a.thumbnail = a.thumbnail or a.url
        else:
            if a.download_html and a.kind != "video":
                # A full snapshot: the page with its styles, images and fonts saved locally.
                from . import snapshot
                try:
                    a.html_content = snapshot.Snapshot(a.id, final).build(body)
                except Exception:
                    snapshot.remove(a.id)
                    a.html_content = nh3.clean(
                        body,
                        tags=nh3.ALLOWED_TAGS | {"article", "section", "header", "footer", "main", "figure", "figcaption"},
                    )
            a.title = a.title or meta_content(body, "og:title", "twitter:title") or page_title(body)
            a.description = a.description or meta_content(body, "og:description", "description", "twitter:description")
            a.author = a.author or meta_content(body, "author", "article:author", "og:site_name")
            thumb = meta_content(body, "og:image", "og:image:url", "twitter:image")
            if thumb and not a.thumbnail:
                a.thumbnail = urljoin(final, thumb)[:2048]
        a.is_processed = True
    except Exception as e:
        a.is_processed = False
        a.error_message = f"Failed to fetch: {e}"[:1000]

    if a.kind == "video":
        try:
            import yt_dlp

            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
                info = ydl.extract_info(a.url, download=False)
            # For videos, the site's own details beat the page's generic tags (on YouTube those
            # name the site as author and can describe a different video).
            found = {
                "title": str(info.get("title") or "")[:500],
                "author": str(info.get("uploader") or info.get("channel") or "")[:255],
                "description": str(info.get("description") or "")[:10000],
                "thumbnail": str(info.get("thumbnail") or "")[:2048],
            }
            for field, value in found.items():
                if value and not had[field]:
                    setattr(a, field, value)
            a.duration = a.duration or info.get("duration")
            a.is_processed = True
            a.error_message = None
        except ImportError:
            pass
        except Exception as e:
            if not a.is_processed:
                a.error_message = f"Failed to read video: {e}"[:1000]
    a.save()


# ------------------------------------------------------------------ views


@api_view(["GET"])
def web_list(request):
    q = request.query_params.get("q", "").strip()
    kind = request.query_params.get("kind", "")
    qs = WebArchive.objects.all()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(url__icontains=q) | Q(notes__icontains=q))
    if kind:
        qs = qs.filter(kind=kind)
    return Response([summary(a) for a in qs.order_by("-created_at")])


@api_view(["POST"])
def web_create(request):
    url = str(request.data.get("url", "")).strip()
    if "://" not in url:
        url = "https://" + url
    err = check_url(url)
    if err:
        return bad(err)
    kind = request.data.get("kind") or detect_kind(url)
    if kind not in ("web", "video", "image", "mixed"):
        return bad("Invalid kind.")
    a = WebArchive.objects.create(
        url=url[:2048],
        kind=kind,
        title=str(request.data.get("title", ""))[:500],
        notes=str(request.data.get("notes", "")),
        download_video=bool(request.data.get("download_video", False)),
        video_format=request.data.get("video_format") or "best",
        video_quality=request.data.get("video_quality") or "",
    )
    process(a)
    return Response(detail(a), status=201)


@api_view(["GET", "PATCH", "DELETE"])
def web_detail(request, archive_id):
    a = get_archive(archive_id)

    if request.method == "DELETE":
        shutil.rmtree(video_dir(a), ignore_errors=True)
        from . import snapshot
        snapshot.remove(a.id)
        a.delete()
        return Response(status=204)

    if request.method == "PATCH":
        d = request.data
        fields = []
        for name, limit in (("title", 500), ("author", 255), ("description", 10000), ("notes", 50000)):
            if name in d:
                setattr(a, name, str(d[name])[:limit])
                fields.append(name)
        if "todos" in d:
            a.todos = clean_todos(d["todos"])
            fields.append("todos")
        if "video_format" in d and d["video_format"] in ("best", "audio"):
            a.video_format = d["video_format"]
            fields.append("video_format")
        if "video_quality" in d and d["video_quality"] in ("", "1080p", "720p", "480p"):
            a.video_quality = d["video_quality"]
            fields.append("video_quality")
        if fields:
            a.save(update_fields=fields + ["updated_at"])
        return Response(detail(a))

    a.last_viewed_at = timezone.now()
    a.save(update_fields=["last_viewed_at"])
    return Response(detail(a))


@api_view(["POST"])
def web_detail_process(request, archive_id):
    """Re-fetch the page and refresh missing metadata."""
    a = get_archive(archive_id)
    process(a)
    return Response(detail(a))


def _download(archive_id: int):
    close_old_connections()
    a = WebArchive.objects.get(id=archive_id)
    try:
        import yt_dlp

        out = video_dir(a)
        shutil.rmtree(out, ignore_errors=True)
        state = {"part": 0, "parts": 1, "last": 0.0}

        def report(**progress):
            # Shared through the database: the page may poll a different worker process.
            WebArchive.objects.filter(id=a.id).update(video_progress=progress)

        def on_progress(d):
            if d.get("status") == "finished":
                state["part"] = min(state["part"] + 1, state["parts"])
                return
            if d.get("status") != "downloading":
                return
            now = time.monotonic()
            if now - state["last"] < 0.5:
                return
            state["last"] = now
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else None
            fmt = d.get("info_dict") or {}
            report(phase="audio" if fmt.get("vcodec") == "none" else "video",
                   part=state["part"] + 1, parts=state["parts"],
                   percent=round(100 * (state["part"] + frac) / state["parts"], 1) if frac is not None else None,
                   downloaded=done, total=total, speed=d.get("speed"), eta=d.get("eta"))

        def on_postprocess(d):
            if d.get("status") == "started" and d.get("postprocessor") in ("Merger", "FFmpegMerger", "VideoConvertor", "FFmpegVideoConvertor"):
                report(phase="merging", percent=100)

        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "outtmpl": out + "/%(id)s.%(ext)s",
                "progress_hooks": [on_progress], "postprocessor_hooks": [on_postprocess]}
        if a.video_format == "audio":
            opts["format"] = "bestaudio/best"
        else:
            h = QUALITY_HEIGHT.get(a.video_quality)
            opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/b" if h else "bv*+ba/b"
            opts["merge_output_format"] = "mp4"
        report(phase="starting")
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Pick formats first, so progress knows how many parts (video + audio) to expect.
            info = ydl.extract_info(a.url, download=False)
            state["parts"] = len(info.get("requested_formats") or []) or 1
            info = ydl.process_ie_result(info, download=True)
            path = ydl.prepare_filename(info)
            if info.get("requested_downloads"):
                path = info["requested_downloads"][0].get("filepath") or path
        a.video_path = str(path).replace(str(settings.MEDIA_ROOT) + "/", "", 1)
        a.video_status = "done"
        a.error_message = None
        a.duration = a.duration or info.get("duration")
    except Exception as e:
        a.video_status = "error"
        a.error_message = f"Download failed: {e}"[:1000]
    a.video_progress = {}
    # Only the download's own fields: notes or a title edited meanwhile are kept.
    a.save(update_fields=["video_path", "video_status", "error_message", "duration", "video_progress", "updated_at"])
    close_old_connections()


@api_view(["POST"])
def web_download_video(request, archive_id):
    """Start a background yt-dlp download; poll the detail endpoint for video_status."""
    a = get_archive(archive_id)
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return bad("yt-dlp is not installed on the server (pip install yt-dlp).", 500)
    if a.video_status == "downloading":
        return bad("Already downloading.", 409)
    err = check_url(a.url)
    if err:
        return bad(err)
    for name in ("video_format", "video_quality"):
        if name in request.data:
            setattr(a, name, request.data[name])
    a.download_video = True
    a.video_status = "downloading"
    a.video_progress = {"phase": "starting"}
    a.error_message = None
    a.save()
    threading.Thread(target=_download, args=(a.id,), daemon=True).start()
    return Response(detail(a), status=202)


@api_view(["GET"])
def web_preview(request, archive_id):
    """Sanitised archived HTML (render it in a sandboxed iframe), or an image/link fallback."""
    a = get_archive(archive_id)
    from .snapshot import is_snapshot
    if is_snapshot(a.html_content):
        return Response({"type": "snapshot", "url": f"/api/web/{a.id}/snapshot"})
    if a.html_content:
        return Response({"type": "html", "content": a.html_content})
    if a.thumbnail:
        return Response({"type": "image", "url": a.thumbnail})
    return Response({"type": "link", "url": a.url})


# Served with a policy that makes the snapshot inert: no scripts, no forms, its own origin (so it
# cannot touch Kern even when opened directly), and nothing loaded from the internet.
SNAPSHOT_CSP = (
    "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; img-src data:; "
    "style-src 'unsafe-inline'; font-src data:; media-src data:; frame-ancestors 'self'; "
    "base-uri 'none'; form-action 'none'"
)


def web_snapshot(request, archive_id):
    """The saved page itself, as HTML, for the bookmark view's iframe."""
    from django.http import HttpResponse

    from .snapshot import is_snapshot, self_contained
    a = get_archive(archive_id)
    if request.method != "GET" or not is_snapshot(a.html_content):
        raise Http404
    r = HttpResponse(self_contained(a.id, a.html_content), content_type="text/html; charset=utf-8")
    r["Content-Security-Policy"] = SNAPSHOT_CSP
    r["X-Content-Type-Options"] = "nosniff"
    r["Referrer-Policy"] = "no-referrer"
    r["Cache-Control"] = "private, no-cache"
    return r
