"""Two-factor sign-in with an authenticator app (TOTP) and recovery codes.

SECURITY (read carefully):
* Seeds are encrypted at rest (kern/secretbox.py).
* A code is accepted once: the last used 30-second step is stored, and that
  step and anything older are refused (no replay within the drift window).
* Recovery codes are random, hashed like passwords and single use.
* A session records that it passed the second step (``SESSION_KEY``). Mail
  requires it (mail/api/guard.py), so a session that only knows the password
  never reaches a mailbox.
"""
from __future__ import annotations

import io
import re
import secrets
import time

import pyotp
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from kern import secretbox

from .models import RecoveryCode, TOTPDevice

STEP = 30
VALID_WINDOW = 1  # accept the previous and next step for clock drift
SESSION_KEY = "kern_2fa"
RECOVERY_RE = re.compile(r"^[a-z0-9]{4}-?[a-z0-9]{4}-?[a-z0-9]{4}$")


def device(user) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user).first()


def enabled(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def secret_of(d: TOTPDevice) -> str:
    return secretbox.decrypt(d.secret_enc)


def start_setup(user) -> tuple[str, str]:
    """A fresh, unconfirmed device. Returns (secret, otpauth URI)."""
    secret = pyotp.random_base32(32)
    TOTPDevice.objects.update_or_create(
        user=user, defaults={"secret_enc": secretbox.encrypt(secret), "confirmed": False, "last_used_step": 0})
    from .site import get_all

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=get_all()["site_name"] or "Kern")
    return secret, uri


def qr_svg(uri: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def verify(user, code: str, now: float | None = None, *, allow_unconfirmed: bool = False) -> bool:
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return False
    now = time.time() if now is None else now
    current = int(now // STEP)
    with transaction.atomic():
        d = TOTPDevice.objects.select_for_update().filter(user=user).first()
        if d is None or (not d.confirmed and not allow_unconfirmed):
            return False
        totp = pyotp.TOTP(secret_of(d))
        for offset in range(-VALID_WINDOW, VALID_WINDOW + 1):
            step = current + offset
            if step <= d.last_used_step:
                continue
            if secrets.compare_digest(totp.at(step * STEP), code):
                d.last_used_step = step
                d.save(update_fields=["last_used_step"])
                return True
    return False


def new_recovery_codes(user, count: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    with transaction.atomic():
        RecoveryCode.objects.filter(user=user).delete()
        for _ in range(count):
            raw = "".join(secrets.choice(alphabet) for _ in range(12))
            codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
            RecoveryCode.objects.create(user=user, code_hash=make_password(raw))
    return codes


def use_recovery_code(user, code: str) -> bool:
    code = (code or "").strip().lower()
    if not RECOVERY_RE.match(code):
        return False
    normalized = code.replace("-", "")
    with transaction.atomic():
        for rc in RecoveryCode.objects.select_for_update().filter(user=user, used_at__isnull=True):
            if check_password(normalized, rc.code_hash):
                rc.used_at = timezone.now()
                rc.save(update_fields=["used_at"])
                return True
    return False


def check_code(user, code: str) -> str:
    """'totp', 'recovery' or '' (wrong)."""
    if verify(user, code):
        return "totp"
    if use_recovery_code(user, code):
        return "recovery"
    return ""


def recovery_left(user) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def disable(user) -> None:
    TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()


def mark_session(request) -> None:
    request.session[SESSION_KEY] = int(time.time())


def session_verified(request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def end_other_sessions(user, keep_key: str | None) -> int:
    """Sign out every other browser and device of this user."""
    n = 0
    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if s.session_key == keep_key:
            continue
        try:
            uid = s.get_decoded().get("_auth_user_id")
        except Exception:
            continue
        if str(uid) == str(user.pk):
            s.delete()
            n += 1
    return n
