"""API views for web archive functionality."""

import json
import os
import re
import tempfile
from datetime import datetime

import requests
from django.db import transaction, models
from django.http import HttpResponse, Http404
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from .models_web import WebArchive
from .views import bad


# ------------------------------------------------------------------ utils


def detect_kind_from_url(url: str) -> str:
    """Detect the content type from URL patterns."""
    url_lower = url.lower()
    
    # Video platforms
    if any(v in url_lower for v in ["youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "tiktok.com"]):
        return "video"
    
    # Image extensions
    ext = re.search(r'\.(jpg|jpeg|png|gif|webp|bmp|svg)$', url, re.IGNORECASE)
    if ext:
        return "image"
    
    return "web"


# ------------------------------------------------------------------ views


@api_view(["GET"])
def web_list(request):
    """List all archived webpages/videos/images."""
    try:
        q = request.query_params.get("q", "")
        kind = request.query_params.get("kind", "")
        
        qs = WebArchive.objects.filter()
        if q:
            qs = qs.filter(
                models.Q(title__icontains=q) | 
                models.Q(description__icontains=q) |
                models.Q(url__icontains=q)
            )
        if kind:
            qs = qs.filter(kind=kind)
        
        archives = list(qs.order_by("-created_at"))
        return Response([{
            "id": str(a.id),
            "url": a.url,
            "title": a.title,
            "kind": a.kind,
            "thumbnail": a.thumbnail,
            "duration": a.duration,
            "author": a.author,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
            "is_processed": a.is_processed,
            "error_message": a.error_message,
        }] for a in archives)
    except Exception as e:
        return bad(str(e), 500)


@api_view(["GET"])
def web_detail(request, archive_id):
    """Get details of an archived item."""
    try:
        archive = WebArchive.objects.get(id=archive_id)
        data = {
            "id": str(archive.id),
            "url": archive.url,
            "title": archive.title,
            "kind": archive.kind,
            "thumbnail": archive.thumbnail,
            "duration": archive.duration,
            "author": archive.author,
            "description": archive.description,
            "html_content": archive.html_content[:2000] + ("..." if len(archive.html_content) > 2000 else ""),
            "download_html": archive.download_html,
            "download_images": archive.download_images,
            "download_video": archive.download_video,
            "video_format": archive.video_format,
            "video_quality": archive.video_quality,
            "notes": archive.notes,
            "todos": archive.todos,
            "is_processed": archive.is_processed,
            "error_message": archive.error_message,
            "created_at": archive.created_at.isoformat(),
            "updated_at": archive.updated_at.isoformat(),
            "last_viewed_at": archive.last_viewed_at.isoformat() if archive.last_viewed_at else None,
        }
        return Response(data)
    except WebArchive.DoesNotExist:
        raise Http404


@api_view(["POST"])
def web_create(request):
    """Create a new web archive entry from a URL."""
    try:
        data = request.data
        url = str(data.get("url", ""))
        
        if not url:
            return bad("URL is required.", 400)
        
        with transaction.atomic():
            kind = data.get("kind") or detect_kind_from_url(url)
            
            archive = WebArchive.objects.create(
                url=url,
                title=str(data.get("title", ""))[:500],
                kind=kind,
                author=str(data.get("author", ""))[:255],
                description=str(data.get("description", "")),
                thumbnail=str(data.get("thumbnail", ""))[:2048],
                download_html=bool(data.get("download_html", True)),
                download_images=bool(data.get("download_images", False)),
                download_video=bool(data.get("download_video", False)),
                video_format=data.get("video_format", "best"),
                video_quality=data.get("video_quality", ""),
                notes=str(data.get("notes", "")),
            )
            
            return Response({
                "id": str(archive.id),
                "url": archive.url,
                "title": archive.title,
                "kind": archive.kind,
            }, status=201)
    except Exception as e:
        return bad(str(e), 500)


@api_view(["GET", "PATCH"])
def web_detail_process(request, archive_id):
    """Process and fetch content for a web archive."""
    try:
        archive = WebArchive.objects.get(id=archive_id)
    except WebArchive.DoesNotExist:
        raise Http404
    
    if request.method == "GET":
        # Fetch HTML/content
        try:
            headers = {}
            auth = None
            
            # Handle authentication URLs
            username = os.environ.get("WEB_ARCHIVE_USER")
            password = os.environ.get("WEB_ARCHIVE_PASS")
            if username and password:
                auth = (username, password)
            
            resp = requests.get(str(archive.url), timeout=30, headers=headers, auth=auth)
            resp.raise_for_status()
            
            archive.html_content = resp.text
            archive.is_processed = True
            
            # Try to extract thumbnail from HTML for all kinds
            try:
                # Try meta og:image first
                meta_thumb_match = re.search(
                    r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\'>]+)', 
                    resp.text, 
                    re.IGNORECASE
                )
                if meta_thumb_match:
                    archive.thumbnail = meta_thumb_match.group(1)[:2048]
                
                # Try og:image:url as fallback
                elif not archive.thumbnail:
                    og_image_url_match = re.search(
                        r'<meta[^>]*property=["\']og:image:url["\'][^>]*content=["\']([^"\'>]+)', 
                        resp.text, 
                        re.IGNORECASE
                    )
                    if og_image_url_match:
                        archive.thumbnail = og_image_url_match.group(1)[:2048]
                
                # Try twitter card image
                elif not archive.thumbnail:
                    twitter_img_match = re.search(
                        r'<meta[^>]*property=["\']twitter:image["\'][^>]*content=["\']([^"\'>]+)', 
                        resp.text, 
                        re.IGNORECASE
                    )
                    if twitter_img_match:
                        archive.thumbnail = twitter_img_match.group(1)[:2048]
                        
            except:
                pass
            
            # Extract video info if it's a video URL
            if archive.kind == "video":
                try:
                    from youtube_dl import YoutubeDL
                    
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': False,
                    }
                    
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(str(archive.url), download=False)
                        
                        archive.title = str(info.get('title', ''))[:500]
                        archive.author = str(info.get('uploader', ''))[:255]
                        archive.duration = info.get('duration')
                        archive.description = str(info.get('description', ''))[:10000]
                        
                        # Get thumbnail from video info
                        if info.get('thumbnail'):
                            archive.thumbnail = str(info.get('thumbnail', ''))[:2048]
                        
                        # Get first video URL
                        formats = info.get('formats', [])
                        if formats:
                            vid_formats = [f for f in formats if 'vcodec' in f.get('format_id', '') or f.get('acodec') == 'none']
                            if vid_formats:
                                best_vid = max(vid_formats, key=lambda x: int(x.get('tbr', 0)))
                                archive.url = best_vid.get('url')
                        
                        # Get description image for thumbnail fallback
                        desc_thumb = info.get('thumbnail_url')
                        if desc_thumb and not archive.thumbnail:
                            archive.thumbnail = str(desc_thumb)[:2048]
                            
                except ImportError:
                    pass  # yt-dlp not available
                    
                except Exception as dl_err:
                    # yt-dlp might fail, that's okay for now - continue with HTML content
                    pass
            
            archive.save()
            
        except requests.RequestException as e:
            if not archive.error_message:
                archive.error_message = f"Failed to fetch: {str(e)}"
            archive.is_processed = False
            archive.save()
            
    elif request.method == "PATCH":
        # Update archive with new notes/todos or processing options
        fields = []
        
        if "notes" in request.data:
            archive.notes = str(request.data["notes"])[:5000]
            fields.append("notes")
        
        if "todos" in request.data:
            archive.todos = [str(t) for t in request.data["todos"]]
            fields.append("todos")
            
        if fields:
            archive.updated_at = datetime.now()
            archive.save(update_fields=fields)
        
        return Response({
            "id": str(archive.id),
            "notes": archive.notes,
            "todos": archive.todos,
        })
    
    archive.last_viewed_at = datetime.now()
    archive.save()
    
    data = {
        "id": str(archive.id),
        "url": archive.url,
        "title": archive.title,
        "kind": archive.kind,
        "thumbnail": archive.thumbnail,
        "duration": archive.duration,
        "author": archive.author,
        "description": archive.description,
        "html_content": archive.html_content[:2000] + ("..." if len(archive.html_content) > 2000 else ""),
        "download_html": archive.download_html,
        "download_images": archive.download_images,
        "download_video": archive.download_video,
        "video_format": archive.video_format,
        "video_quality": archive.video_quality,
        "notes": archive.notes,
        "todos": archive.todos,
        "is_processed": archive.is_processed,
        "error_message": archive.error_message,
    }
    
    return Response(data)


@api_view(["POST"])
def web_download_video(request, archive_id):
    """Download video using yt-dlp with specified options."""
    try:
        archive = WebArchive.objects.get(id=archive_id)
    except WebArchive.DoesNotExist:
        raise Http404
    
    if not archive.download_video:
        return bad("Video download is not enabled for this item.", 400)
    
    try:
        from youtube_dl import YoutubeDL
        
        url = str(archive.url)
        
        # Build options
        ydl_opts = {
            'quiet': False,  # Show progress
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,  # We'll download manually
            'format': '',
            'outtmpl': tempfile.gettempdir() + '/%_(title)s.%(ext)s',
        }
        
        # Apply format selection if video_format is set
        if archive.video_format == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif archive.video_format == "best" and archive.video_quality:
            q_map = {"1080p": "best[height<=1080]", "720p": "best[height<=720]", "480p": "best[height<=480]"}
            ydl_opts['format'] = q_map.get(archive.video_quality, 'best')
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            archive.download_video = True
            archive.is_processed = True
            archive.save()
            
            return Response({
                "status": "success",
                "message": f"Video downloaded from {archive.title or archive.url}",
            })
        except Exception as dl_err:
            if not archive.error_message:
                archive.error_message = str(dl_err)
            archive.download_video = False
            archive.is_processed = True
            archive.save()
            
            return bad(f"yt-dlp error: {str(dl_err)}", 500)
            
    except ImportError:
        return bad("yt-dlp is not installed. Run: pip install youtube-dlc yt_dlp", 500)
    
    except Exception as e:
        if not archive.error_message:
            archive.error_message = str(e)
        archive.save()
        return bad(str(e), 500)


@api_view(["GET"])
def web_preview(request, archive_id):
    """Get a preview of the archived content."""
    try:
        archive = WebArchive.objects.get(id=archive_id)
    except WebArchive.DoesNotExist:
        raise Http404
    
    if archive.kind == "image" and archive.thumbnail:
        # Return thumbnail info
        return Response({
            "type": "url",
            "url": str(archive.thumbnail),
            "mimeType": archive.image_mime or "",
        })
    
    if archive.html_content:
        # Return HTML preview with sanitization
        sanitized = archive.html_content[:5000] + ("..." if len(archive.html_content) > 5000 else "")
        return Response({
            "type": "html",
            "content": sanitized,
        })
    
    if archive.thumbnail:
        return Response({
            "type": "url",
            "url": str(archive.thumbnail),
        })
    
    return Response({
        "type": "link",
        "url": archive.url,
    })
