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


class GitToken(models.Model):
    """An access token for one git repository of one user.

    Lives in the shared database so a request can find it from the token alone (`kern_<id>_<secret>`)
    without scanning every user's data. Only a hash of the secret is stored; it is shown once."""

    owner = models.IntegerField(db_index=True)       # the owner's user id (their tenant)
    repo = models.CharField(max_length=64)
    label = models.CharField(max_length=60)
    scope = models.CharField(max_length=5, choices=[("read", "read"), ("write", "write")])
    secret_hash = models.CharField(max_length=64)    # sha256 of the secret (a long random string)
    created = models.DateTimeField(auto_now_add=True)
    expires = models.DateTimeField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "repo"])]


class SSHKey(models.Model):
    """A public key that may sign in to Kern's git-over-SSH server. Lives in the shared database
    because the key is looked up before anyone is known. ``repo`` empty: an account key (every
    repository of ``user``); otherwise a deploy key for that one repository."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ssh_keys")
    repo = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=80)
    key_type = models.CharField(max_length=40)
    public_key = models.TextField()  # normalized "<type> <base64>"
    fingerprint = models.CharField(max_length=80, unique=True)  # "SHA256:…"; one registration per server
    read_only = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
