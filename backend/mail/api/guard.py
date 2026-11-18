"""Who may use /api/mail.

SECURITY (read carefully): Kern's AccessMiddleware has already required a
signed-in, active user and switched to their own database. On top of that,
mail requires two-factor sign-in: the account must have an authenticator set
up AND this session must have passed the second step (accounts/totp.py). A
session that only knows the password (signed in before two-factor was turned
on, or a stolen password) can't read or send mail.

Only the account status endpoint is open without it, so Settings → Mail can
explain what's missing.
"""
from __future__ import annotations

from django.http import JsonResponse

OPEN = {"/api/mail/account/status"}


class MailGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not path.startswith("/api/mail/") or path.rstrip("/") in OPEN:
            return self.get_response(request)
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.is_active):
            return self.get_response(request)  # AccessMiddleware answers 401
        from accounts import totp

        if not totp.enabled(user):
            return JsonResponse({"detail": "Mail needs two-factor sign-in. Turn it on in Settings → Account.",
                                 "code": "needs_2fa"}, status=403)
        if not totp.session_verified(request):
            return JsonResponse({"detail": "Sign out and in again with your authenticator code to use mail.",
                                 "code": "needs_2fa_session"}, status=403)
        return self.get_response(request)
