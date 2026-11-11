from django.urls import include, path, re_path

from notes.views_files import serve_media
from notes.views_git import git_entry

urlpatterns = [
    path("api/", include("accounts.urls")),
    path("api/", include("notes.urls")),
    # Git smart-HTTP protocol (clone/fetch/push). Lives outside /api on purpose: git
    # clients cannot send the X-Kern header that ApiGuardMiddleware requires there.
    re_path(r"^git/(?P<subpath>.+)$", git_entry),
    # In Docker the web container serves /media directly; this is the fallback (range-aware).
    re_path(r"^media/(?P<path>.*)$", serve_media),
]
