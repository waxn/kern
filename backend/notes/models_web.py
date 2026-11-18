"""Web archive storage model - separate from main models."""

import uuid
from datetime import datetime
from django.db import models


class WebArchive(models.Model):
    """A saved webpage, video, or image captured from a URL."""
    
    # Content source and type
    url = models.URLField(max_length=2048, db_index=True)
    title = models.CharField(max_length=500, blank=True, default="")
    kind = models.CharField(
        max_length=16,
        choices=[
            ("web", "Webpage"),
            ("video", "Video"),
            ("image", "Image"),
            ("mixed", "Mixed"),
        ],
        default="web"
    )
    
    # Content metadata
    thumbnail = models.URLField(max_length=2048, blank=True, default="")
    duration = models.FloatField(null=True, blank=True)  # in seconds, for videos
    author = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    
    # Content data
    html_content = models.TextField(blank=True, default="")  # fetched HTML
    image_mime = models.CharField(max_length=64, blank=True, default="")  # MIME for thumbnail if local
    
    # Download settings
    download_html = models.BooleanField(default=True)        # save webpage content
    download_images = models.BooleanField(default=False)     # save images from page
    download_video = models.BooleanField(default=False)      # download video if available
    video_format = models.CharField(
        max_length=8,
        choices=[("best", "Best"), ("audio", "Audio only")],
        blank=True,
        default="best"
    )
    video_quality = models.CharField(
        max_length=16,
        choices=[("1080p", "1080p"), ("720p", "720p"), ("480p", "480p")],
        blank=True,
        default=""
    )
    
    video_path = models.CharField(max_length=500, blank=True, default="")  # relative to MEDIA_ROOT
    video_status = models.CharField(max_length=16, blank=True, default="")  # "", downloading, done, error
    # While downloading: {"phase", "part", "parts", "percent", "downloaded", "total", "speed", "eta"}
    video_progress = models.JSONField(default=dict, blank=True)

    # Notes and tasks
    notes = models.TextField(blank=True, default="")
    todos = models.JSONField(default=list, blank=True)  # list of strings
    
    # Status and metadata
    is_processed = models.BooleanField(default=False)        # has content been saved
    error_message = models.TextField(null=True, blank=True)
    
    tags = models.ManyToManyField("notes.Tag", blank=True, related_name="bookmarks")

    # Watching the page for changes (see notes/monitor.py)
    monitor_enabled = models.BooleanField(default=False)
    # auto: decided on the first check; posts: new entries in its feed or post list;
    # price: the product's price; content: any change to the page's text.
    monitor_mode = models.CharField(max_length=16, default="auto")
    monitor_interval = models.PositiveIntegerField(default=1440)  # minutes
    monitor_archive = models.BooleanField(default=True)  # save a snapshot to history on each change
    # Baseline from the last check: {"mode", "feed_url", "seen": [...], "hash", "text", "price": {...}}
    monitor_state = models.JSONField(default=dict, blank=True)
    monitor_error = models.TextField(blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_changed_at = models.DateTimeField(null=True, blank=True)
    unseen_changes = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["url"]), models.Index(fields=["kind"])]


class WebSnapshot(models.Model):
    """One saved version of a bookmarked page, like an entry in the Wayback Machine.

    Its page assets live in ``MEDIA_ROOT/web-pages/v<id>/``, hard-linked from the capture they
    came from, so versions that share images and fonts share the disk space too.
    """

    archive = models.ForeignKey(WebArchive, on_delete=models.CASCADE, related_name="snapshots")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # saved: when bookmarked; manual: "Save snapshot now"; change: a check found a change; refetch
    trigger = models.CharField(max_length=16, default="manual")
    url = models.URLField(max_length=2048, blank=True, default="")  # the page's address after redirects
    title = models.CharField(max_length=500, blank=True, default="")
    html = models.TextField(blank=True, default="")  # the page as saved (a snapshot, or sanitised HTML)
    text = models.TextField(blank=True, default="")  # its readable text, for comparing versions
    text_hash = models.CharField(max_length=64, blank=True, default="")
    # What the check that saved it saw: {"type": "posts"|"price"|"content", ...}
    change = models.JSONField(default=dict, blank=True)
    price = models.CharField(max_length=64, blank=True, default="")
    size = models.PositiveIntegerField(default=0)  # bytes of html + assets

    class Meta:
        ordering = ["-created_at", "-id"]
