from django.http import JsonResponse

SAFE = {"GET", "HEAD", "OPTIONS"}


class ApiGuardMiddleware:
    """Require a custom header on mutating API calls.

    The app has no login, so this stops other websites open in the same
    browser from issuing cross-site writes (a custom header forces a CORS
    preflight, which is never granted).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith("/api/")
            and request.method not in SAFE
            and request.headers.get("X-Kern") != "1"
        ):
            return JsonResponse({"detail": "Missing X-Kern header."}, status=403)
        return self.get_response(request)
