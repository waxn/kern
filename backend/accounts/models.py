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
