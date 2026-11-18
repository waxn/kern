from django.conf import settings
from django.db import models


class SiteSetting(models.Model):
    """Server-wide configuration chosen during setup (shared by every user)."""

    key = models.CharField(max_length=80, primary_key=True)
    value = models.JSONField(null=True)


class Throttle(models.Model):
    """Failed-attempt counters for sign-in, setup and git password checks."""

    key = models.CharField(max_length=200, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)


class TOTPDevice(models.Model):
    """An authenticator app (two-factor sign-in). The seed is encrypted with
    kern/secretbox.py, so a copy of the accounts database alone can't mint codes.
    ``confirmed`` turns on once the user has entered a first code."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp")
    secret_enc = models.TextField()
    confirmed = models.BooleanField(default=False)
    # Last accepted 30-second step; codes at or before it are refused (replay).
    last_used_step = models.BigIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)


class RecoveryCode(models.Model):
    """Single-use backup codes for two-factor sign-in, stored hashed."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=256)
    used_at = models.DateTimeField(null=True, blank=True)
