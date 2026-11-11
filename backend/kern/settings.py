import os
import secrets
from pathlib import Path

import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if "test" in sys.argv:
    os.environ.setdefault("KERN_NO_AUTO_BACKUP", "1")
DATA_DIR = Path(os.environ.get("KERN_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Each user's database, files and repositories live in DATA_DIR/users/<id>/ (see kern/tenancy.py).
KERN_TESTING = "test" in sys.argv
HTTPS = os.environ.get("KERN_HTTPS", "0") == "1"  # served over HTTPS (by a proxy in front)


def _secret_key() -> str:
    env = os.environ.get("KERN_SECRET_KEY")
    if env:
        return env
    path = DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("KERN_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "rest_framework",
    "accounts",
    "notes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "kern.middleware.ApiGuardMiddleware",
    "kern.middleware.AccessMiddleware",
]

# ---- accounts and sessions
SESSION_COOKIE_NAME = "kern_sid"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if HTTPS else None
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
DATABASE_ROUTERS = ["kern.router.TenantRouter"]
STORAGES = {
    "default": {"BACKEND": "kern.storage.TenantStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

ROOT_URLCONF = "kern.urls"
WSGI_APPLICATION = "kern.wsgi.application"
TEMPLATES = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "accounts.sqlite3",  # accounts, sessions, site settings
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA foreign_keys=ON;"
                "PRAGMA busy_timeout=20000;"
            ),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

MEDIA_ROOT = DATA_DIR / "media"
MEDIA_URL = "/media/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.auth.SessionUser"],
    "DEFAULT_PERMISSION_CLASSES": ["accounts.auth.IsSignedIn"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

# Extra host names (comma separated) allowed as the Origin of writes, e.g. when a proxy rewrites Host.
KERN_TRUSTED_HOSTS = os.environ.get("KERN_TRUSTED_HOSTS", "").split(",")
