"""Slow down password guessing: too many failures lock the username (and the address) for a while."""
import datetime as dt

from django.utils import timezone

from .models import Throttle

WINDOW = dt.timedelta(minutes=15)
LOCK = dt.timedelta(minutes=15)


def client_ip(request) -> str:
    addr = request.META.get("REMOTE_ADDR", "") or "?"
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    # The web container (Caddy) sets this header from the real connection; only trust it from a
    # private/loopback hop, never from a client talking to us directly.
    if fwd and (addr.startswith(("10.", "127.", "192.168.", "172.")) or addr in ("::1", "?")):
        return fwd.split(",")[0].strip()[:64] or addr
    return addr[:64]


def locked(key: str) -> int:
    """Seconds left on a lock, or 0."""
    t = Throttle.objects.filter(key=key).first()
    if t and t.locked_until and t.locked_until > timezone.now():
        return int((t.locked_until - timezone.now()).total_seconds()) + 1
    return 0


def fail(key: str, limit: int) -> None:
    now = timezone.now()
    t, _ = Throttle.objects.get_or_create(key=key, defaults={"window_start": now})
    if now - t.window_start > WINDOW:
        t.count, t.window_start, t.locked_until = 0, now, None
    t.count += 1
    if t.count >= limit:
        t.locked_until = now + LOCK
        t.count = 0
        t.window_start = now
    t.save()


def clear(key: str) -> None:
    Throttle.objects.filter(key=key).delete()
