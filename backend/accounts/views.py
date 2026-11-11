import os
import re
import shutil

from django.conf import settings
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from kern import tenancy

from . import site, throttle
from .auth import IsAdmin

BACKEND = "django.contrib.auth.backends.ModelBackend"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
_dummy_hash = None


def bad(msg, status=400, **extra):
    return Response({"detail": msg, **extra}, status=status)


def user_json(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "email": u.email, "is_admin": u.is_staff,
        "is_active": u.is_active, "date_joined": u.date_joined, "last_login": u.last_login,
    }


def site_json(request, user=None) -> dict:
    u = user if user is not None else getattr(request, "user", None)
    signed_in = bool(u and u.is_authenticated and u.is_active)
    cfg = site.get_all()
    return {
        "needs_setup": not site.setup_complete(),
        "site_name": cfg["site_name"],
        "landing_enabled": cfg["landing_enabled"],
        "signup_mode": cfg["signup_mode"],
        "allow_git": cfg["allow_git"],
        "user": user_json(u) if signed_in else None,
    }


def check_username(name: str, exclude_id=None) -> str:
    name = str(name or "").strip()
    if not USERNAME_RE.match(name):
        raise ValueError("Usernames are 3–32 characters: letters, digits, dots, dashes and underscores.")
    q = User.objects.filter(username__iexact=name)
    if exclude_id:
        q = q.exclude(id=exclude_id)
    if q.exists():
        raise ValueError("That username is taken.")
    return name


def check_password_ok(pw: str, username="", email="") -> str:
    pw = str(pw or "")
    try:
        validate_password(pw, User(username=username, email=email))
    except ValidationError as e:
        raise ValueError(" ".join(e.messages))
    return pw


def check_email(email) -> str:
    email = str(email or "").strip()[:254]
    if email:
        try:
            validate_email(email)
        except ValidationError:
            raise ValueError("That email address does not look right.")
    return email


def sign_in(request, user: User) -> None:
    login(request._request, user, backend=BACKEND)


def adopt_legacy_data(user: User) -> bool:
    """Installs from before accounts existed kept everything in the data folder. The first admin
    takes that over, so nothing is lost when upgrading."""
    if tenancy.testing():
        return False
    root = settings.DATA_DIR
    legacy = root / "kern.sqlite3"
    if not legacy.exists():
        return False
    dest = tenancy.user_dir(user.id)
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("kern.sqlite3", "kern.sqlite3-wal", "kern.sqlite3-shm"):
        if (root / name).exists() and not (dest / name).exists():
            shutil.move(str(root / name), str(dest / name))
    for name in ("media", "git", "backups"):
        src, dst = root / name, dest / name
        if src.is_dir() and not dst.exists():
            shutil.move(str(src), str(dst))
    return True


# ------------------------------------------------------------------ public


@api_view(["GET"])
@permission_classes([AllowAny])
def site_info(request):
    return Response(site_json(request))


@api_view(["POST"])
@permission_classes([AllowAny])
def setup(request):
    """First run: create the first administrator and choose how the server behaves."""
    if site.setup_complete():
        return bad("Setup is already finished.", 409)
    ip_key = f"setup:{throttle.client_ip(request)}"
    wait = throttle.locked(ip_key)
    if wait:
        return bad("Too many attempts. Try again later.", 429, retry_after=wait)
    data = request.data if isinstance(request.data, dict) else {}
    if not site.check_setup_code(data.get("code")):
        throttle.fail(ip_key, 8)
        return bad("That setup code is not right. It is printed in the server log.", 403)
    try:
        username = check_username(data.get("username"))
        email = check_email(data.get("email"))
        password = check_password_ok(data.get("password"), username, email)
        cfg = data.get("site") if isinstance(data.get("site"), dict) else {}
        with transaction.atomic():
            if site.setup_complete():
                return bad("Setup is already finished.", 409)
            user = User.objects.create_user(username=username, email=email, password=password,
                                            is_staff=True, is_superuser=True)
            site.update(cfg)
            site.mark_setup_complete()
    except ValueError as e:
        return bad(str(e))
    adopt_legacy_data(user)
    tenancy.ensure_db(user.id)
    site.retire_setup_code()
    throttle.clear(ip_key)
    sign_in(request, user)
    return Response(site_json(request, user), status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    if not site.setup_complete():
        return bad("Finish setup first.", 409)
    data = request.data if isinstance(request.data, dict) else {}
    username = str(data.get("username") or "").strip()[:150]
    password = str(data.get("password") or "")[:1024]
    ukey = f"login:u:{username.lower()}"
    ikey = f"login:ip:{throttle.client_ip(request)}"
    wait = max(throttle.locked(ukey), throttle.locked(ikey))
    if wait:
        return bad(f"Too many failed attempts. Try again in {max(1, wait // 60)} min.", 429, retry_after=wait)
    user = User.objects.filter(username__iexact=username).first() if username else None
    global _dummy_hash
    if user is None:
        # Spend the same time as a real check so usernames cannot be probed by timing.
        _dummy_hash = _dummy_hash or make_password("kern-dummy")
        check_password(password, _dummy_hash)
        ok = False
    else:
        ok = user.check_password(password)
    if not ok:
        throttle.fail(ukey, 8)
        throttle.fail(ikey, 60)
        return bad("Wrong username or password.", 401)
    if not user.is_active:
        return bad("This account is waiting for an administrator's approval, or has been disabled.", 403)
    throttle.clear(ukey)
    tenancy.ensure_db(user.id)
    sign_in(request, user)
    return Response(site_json(request, user))


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    logout(request._request)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def signup(request):
    if not site.setup_complete():
        return bad("Finish setup first.", 409)
    mode = site.get_all()["signup_mode"]
    if mode == "closed":
        return bad("Sign-ups are closed. Ask an administrator for an account.", 403)
    ikey = f"signup:{throttle.client_ip(request)}"
    wait = throttle.locked(ikey)
    if wait:
        return bad("Too many sign-ups from here. Try again later.", 429, retry_after=wait)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        username = check_username(data.get("username"))
        email = check_email(data.get("email"))
        password = check_password_ok(data.get("password"), username, email)
    except ValueError as e:
        return bad(str(e))
    try:
        user = User.objects.create_user(username=username, email=email, password=password,
                                        is_active=(mode == "open"))
    except Exception:
        return bad("That username is taken.")
    throttle.fail(ikey, 10)
    if mode == "approval":
        return Response({"pending": True}, status=202)
    tenancy.ensure_db(user.id)
    sign_in(request, user)
    return Response(site_json(request, user), status=201)


# ------------------------------------------------------------------ signed in


@api_view(["POST"])
def change_password(request):
    user = request.user
    data = request.data if isinstance(request.data, dict) else {}
    key = f"pw:{user.id}"
    wait = throttle.locked(key)
    if wait:
        return bad("Too many attempts. Try again later.", 429, retry_after=wait)
    if not user.check_password(str(data.get("current") or "")):
        throttle.fail(key, 6)
        return bad("Your current password is wrong.", 403)
    try:
        pw = check_password_ok(data.get("new"), user.username, user.email)
    except ValueError as e:
        return bad(str(e))
    user.set_password(pw)
    user.save(update_fields=["password"])
    update_session_auth_hash(request._request, user)  # this browser stays signed in; others do not
    throttle.clear(key)
    return Response({"ok": True})


@api_view(["PATCH"])
def update_profile(request):
    data = request.data if isinstance(request.data, dict) else {}
    try:
        if "email" in data:
            request.user.email = check_email(data["email"])
            request.user.save(update_fields=["email"])
    except ValueError as e:
        return bad(str(e))
    return Response(user_json(request.user))


# ------------------------------------------------------------------ administrators


def _dir_size(path) -> int:
    total = 0
    for dp, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def _other_admins(exclude_id) -> int:
    return User.objects.filter(is_staff=True, is_active=True).exclude(id=exclude_id).count()


@api_view(["GET", "POST"])
@permission_classes([IsAdmin])
def admin_users(request):
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        try:
            username = check_username(data.get("username"))
            email = check_email(data.get("email"))
            password = check_password_ok(data.get("password"), username, email)
        except ValueError as e:
            return bad(str(e))
        admin = bool(data.get("is_admin"))
        u = User.objects.create_user(username=username, email=email, password=password,
                                     is_staff=admin, is_superuser=admin)
        tenancy.ensure_db(u.id)
        return Response(user_json(u), status=201)
    out = []
    for u in User.objects.order_by("date_joined"):
        j = user_json(u)
        d = tenancy.user_dir(u.id)
        j["storage_bytes"] = _dir_size(d) if d.exists() else 0
        out.append(j)
    return Response(out)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAdmin])
def admin_user_detail(request, user_id):
    u = User.objects.filter(id=user_id).first()
    if not u:
        return bad("No such user.", 404)
    me = request.user
    if request.method == "DELETE":
        if u.id == me.id:
            return bad("You cannot delete your own account.")
        if u.is_staff and u.is_active and not _other_admins(u.id):
            return bad("There must be at least one administrator.")
        tenancy.forget_db(u.id)
        shutil.rmtree(tenancy.user_dir(u.id), ignore_errors=True)
        u.delete()
        return Response(status=204)
    data = request.data if isinstance(request.data, dict) else {}
    losing_admin = (("is_admin" in data and not data["is_admin"]) or ("is_active" in data and not data["is_active"]))
    if losing_admin and u.is_staff and u.is_active and not _other_admins(u.id):
        return bad("There must be at least one administrator.")
    if u.id == me.id and "is_active" in data and not data["is_active"]:
        return bad("You cannot disable your own account.")
    try:
        if "email" in data:
            u.email = check_email(data["email"])
        if data.get("password"):
            u.set_password(check_password_ok(data["password"], u.username, u.email))
    except ValueError as e:
        return bad(str(e))
    if "is_admin" in data:
        u.is_staff = u.is_superuser = bool(data["is_admin"])
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
        if u.is_active:
            tenancy.ensure_db(u.id)
    u.save()
    return Response(user_json(u))


@api_view(["GET", "PATCH"])
@permission_classes([IsAdmin])
def admin_site(request):
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        try:
            return Response(site.update(data))
        except ValueError as e:
            return bad(str(e))
    return Response(site.get_all())
