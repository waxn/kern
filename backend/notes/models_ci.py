"""CI runs for hosted git repositories (see notes/ci.py). Per-user tables, like everything in notes."""
from django.db import models


class Run(models.Model):
    QUEUED, RUNNING, SUCCESS, FAILED, CANCELLED, ERROR = "queued", "running", "success", "failed", "cancelled", "error"
    FINISHED = (SUCCESS, FAILED, CANCELLED, ERROR)

    repo = models.CharField(max_length=64, db_index=True)
    ref = models.CharField(max_length=300)  # full name: refs/heads/main, refs/tags/v1
    sha = models.CharField(max_length=64)
    subject = models.CharField(max_length=300, blank=True, default="")  # first line of the commit message
    trigger = models.CharField(max_length=12, default="push")  # push | manual | rerun
    pusher = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(max_length=12, default=QUEUED, db_index=True)
    error = models.TextField(blank=True, default="")  # why a run is in the "error" state
    pipeline = models.JSONField(null=True, blank=True)  # the parsed pipeline file, as read from the commit
    cancel_requested = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["repo", "sha"]), models.Index(fields=["repo", "ref"])]

    @property
    def branch(self):
        return self.ref[len("refs/heads/"):] if self.ref.startswith("refs/heads/") else None

    @property
    def tag(self):
        return self.ref[len("refs/tags/"):] if self.ref.startswith("refs/tags/") else None


class Job(models.Model):
    PENDING, RUNNING, SUCCESS, FAILED, SKIPPED, CANCELLED, ERROR = (
        "pending", "running", "success", "failed", "skipped", "cancelled", "error")

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="jobs")
    name = models.CharField(max_length=64)
    position = models.IntegerField(default=0)
    status = models.CharField(max_length=12, default=PENDING)
    note = models.CharField(max_length=300, blank=True, default="")  # e.g. "timed out after 30 min"
    exit_code = models.IntegerField(null=True, blank=True)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        unique_together = [("run", "name")]


class CISecret(models.Model):
    """A secret of one repository, encrypted with kern.secretbox. Never sent to the browser."""

    repo = models.CharField(max_length=64)
    name = models.CharField(max_length=64)
    value_enc = models.TextField()
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("repo", "name")]
