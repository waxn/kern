"""Server-wide settings (chosen in the setup wizard, editable by admins) and the setup code."""
import os
import secrets
from pathlib import Path

from django.conf import settings
from django.utils.crypto import constant_time_compare

from .models import SiteSetting

DEFAULTS = {
    "site_name": "Kern",
    "landing_enabled": False,   # show a public landing page at / to people who are not signed in
    "signup_mode": "closed",    # closed | open | approval
    "allow_git": True,          # let users host git repositories
}
SIGNUP_MODES = ("closed", "open", "approval")


def get_all() -> dict:
    out = dict(DEFAULTS)
    for s in SiteSetting.objects.exclude(key="setup_complete"):
        if s.key in DEFAULTS:
            out[s.key] = s.value
    return out


def update(values: dict) -> dict:
    """Validate and save the known settings in values; returns the full set."""
    clean = {}
    if "site_name" in values:
        name = str(values["site_name"] or "").strip()[:60]
        clean["site_name"] = name or DEFAULTS["site_name"]
    for k in ("landing_enabled", "allow_git"):
        if k in values:
            clean[k] = bool(values[k])
    if "signup_mode" in values:
        if values["signup_mode"] not in SIGNUP_MODES:
            raise ValueError("Sign-ups must be closed, open or need approval.")
        clean["signup_mode"] = values["signup_mode"]
    for k, v in clean.items():
        SiteSetting.objects.update_or_create(key=k, defaults={"value": v})
    return get_all()


def setup_complete() -> bool:
    return SiteSetting.objects.filter(key="setup_complete", value=True).exists()


def mark_setup_complete() -> None:
    SiteSetting.objects.update_or_create(key="setup_complete", defaults={"value": True})


# ------------------------------------------------------------------ setup code
# Whoever can reach the port first could otherwise claim the server. The setup code is printed in
# the server log (and stored in the data folder), so only someone with access to the server can
# finish setup.


def _token_path() -> Path:
    return Path(settings.DATA_DIR) / "setup_code"


def setup_code() -> str:
    env = os.environ.get("KERN_SETUP_CODE", "").strip()
    if env:
        return env
    p = _token_path()
    if not p.exists():
        p.write_text(secrets.token_hex(4).upper())
        p.chmod(0o600)
    return p.read_text().strip()


def check_setup_code(given: str) -> bool:
    return constant_time_compare(str(given or "").strip().upper(), setup_code().upper())


def retire_setup_code() -> None:
    _token_path().unlink(missing_ok=True)
