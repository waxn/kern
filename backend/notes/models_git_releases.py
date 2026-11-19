"""Releases for hosted git repositories: a tag plus notes and attached files.

Files live under ``<user data dir>/git-releases/<repo>/<release id>/<filename>``, outside the
bare repository, so they are not part of the git data. Logic lives in :mod:`notes.git_releases`.
"""
from django.db import models


class Release(models.Model):
    repo = models.CharField(max_length=64, db_index=True)
    tag = models.CharField(max_length=250)
    title = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    draft = models.BooleanField(default=False)
    prerelease = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    published = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created", "-id"]
        constraints = [models.UniqueConstraint(fields=["repo", "tag"], name="git_release_unique_tag")]


class ReleaseAsset(models.Model):
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="assets")
    filename = models.CharField(max_length=255)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="application/octet-stream")
    downloads = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["filename", "id"]
        constraints = [models.UniqueConstraint(fields=["release", "filename"], name="git_asset_unique_name")]
