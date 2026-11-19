"""Push mirrors and webhooks of hosted git repositories (per user; see gitmirrors.py, gitwebhooks.py).

Secrets (the mirror's token, the webhook's signing secret) are stored encrypted with
``kern.secretbox`` and never sent back to the browser."""
import uuid

from django.db import models


class GitMirror(models.Model):
    repo = models.CharField(max_length=64, db_index=True)
    url = models.CharField(max_length=500)
    username = models.CharField(max_length=200, blank=True, default="")
    secret_enc = models.TextField(blank=True, default="")  # the token or password, encrypted
    enabled = models.BooleanField(default=True)
    only_protected = models.BooleanField(default=False)  # push only the protected branches (and tags)
    branch_filter = models.CharField(max_length=500, blank=True, default="")  # space separated patterns
    last_attempt = models.DateTimeField(null=True, blank=True)
    last_success = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class GitWebhook(models.Model):
    repo = models.CharField(max_length=64, db_index=True)
    url = models.CharField(max_length=500)
    secret_enc = models.TextField(blank=True, default="")  # signing secret, encrypted
    events = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class GitWebhookDelivery(models.Model):
    hook = models.ForeignKey(GitWebhook, on_delete=models.CASCADE, related_name="deliveries")
    guid = models.UUIDField(default=uuid.uuid4, editable=False)
    event = models.CharField(max_length=40)
    status_code = models.IntegerField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    attempts = models.IntegerField(default=1)
    duration_ms = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")
    request_headers = models.JSONField(default=dict)
    request_body = models.TextField(blank=True, default="")
    response_body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
