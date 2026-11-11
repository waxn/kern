from urllib.parse import urlparse

from django.conf import settings
from django.http import JsonResponse

from . import tenancy

SAFE = {"GET", "HEAD", "OPTIONS"}

# Reachable without signing in. Everything else under /api and /media needs a signed-in, active user.
PUBLIC = {"/api/health", "/api/site", "/api/setup", "/api/setup/restore", "/api/auth/login", "/api/auth/logout", "/api/auth/signup"}


class ApiGuardMiddleware:
    """Stop other websites from acting as the signed-in user.

    Writes need a custom header (which forces a CORS preflight that is never granted), and a
    request that names its origin must come from this site. Session cookies are also SameSite=Lax.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method not in SAFE:
            if request.headers.get("X-Kern") != "1":
                return JsonResponse({"detail": "Missing X-Kern header."}, status=403)
            if not self._from_this_site(request):
                return JsonResponse({"detail": "Cross-site request refused."}, status=403)
        return self.get_response(request)

    def _from_this_site(self, request) -> bool:
        # Browsers say where a request came from (Sec-Fetch-Site), which works behind any proxy.
        fetch_site = request.headers.get("Sec-Fetch-Site")
        if fetch_site:
            return fetch_site in ("same-origin", "none")
        origin = request.headers.get("Origin")  # older clients: compare the Origin with our host
        return not origin or origin == "null" or self._same_host(request, origin)

    @staticmethod
    def _same_host(request, origin: str) -> bool:
        host = urlparse(origin).netloc
        if host == request.get_host():
            return True
        trusted = [h.strip() for h in getattr(settings, "KERN_TRUSTED_HOSTS", []) if h.strip()]
        return host in trusted or host == request.headers.get("X-Forwarded-Host", "")


class AccessMiddleware:
    """Require a signed-in user for the API and uploaded files, and run the request as that user
    (their own database, files and repositories). Git clients sign in themselves with HTTP Basic."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/git/"):
            return self.get_response(request)
        if path.startswith("/api/") or path.startswith("/media/"):
            if path.rstrip("/") in PUBLIC:
                return self.get_response(request)
            user = request.user
            if not (user.is_authenticated and user.is_active):
                r = JsonResponse({"detail": "Sign in to continue."}, status=401)
                r["Cache-Control"] = "no-store"
                return r
            with tenancy.use(user.id):
                response = self.get_response(request)
            if path.startswith("/api/") and "Cache-Control" not in response:
                response["Cache-Control"] = "private, no-cache"
            return response
        return self.get_response(request)
