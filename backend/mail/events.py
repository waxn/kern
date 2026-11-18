"""Change feed helpers (consumed by the SSE endpoint)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import ChangeEvent


def emit(kind: str, **data) -> None:
    ChangeEvent.objects.create(kind=kind, data=data)


def prune(days: int = 2) -> None:
    ChangeEvent.objects.filter(created__lt=timezone.now() - timedelta(days=days)).delete()
