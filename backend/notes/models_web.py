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
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["url"]), models.Index(fields=["kind"])]
