from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission


class SessionUser(BaseAuthentication):
    """Use the user Django's session middleware found. CSRF is covered by the X-Kern header and
    Origin checks in ApiGuardMiddleware, so DRF's own CSRF enforcement is not needed."""

    def authenticate(self, request):
        user = getattr(request._request, "user", None)
        if user is not None and user.is_authenticated and user.is_active:
            return (user, None)
        return None


class IsSignedIn(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active)


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_staff)
