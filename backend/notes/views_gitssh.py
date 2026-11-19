"""JSON API for SSH keys: account keys (all your repositories) and per-repository deploy keys."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts import sshkeys
from accounts.models import SSHKey

from . import gitrepo as g
from .views import bad
from .views_git import handle


def _add(request, repo="", read_only=False):
    data = request.data if isinstance(request.data, dict) else {}
    try:
        k = sshkeys.add(request.user, data.get("title"), data.get("key"), repo=repo,
                        read_only=bool(data.get("read_only")) if repo else False)
    except ValueError as e:
        return bad(str(e))
    return Response(sshkeys.as_json(k), status=201)


@api_view(["GET", "POST"])
def ssh_keys(request):
    if request.method == "POST":
        return _add(request)
    qs = SSHKey.objects.filter(user=request.user, repo="").order_by("created", "id")
    return Response([sshkeys.as_json(k) for k in qs])


@api_view(["DELETE"])
def ssh_key(request, key_id):
    n, _ = SSHKey.objects.filter(pk=key_id, user=request.user, repo="").delete()
    return Response(status=204) if n else bad("No such key.", 404)


@api_view(["GET", "POST"])
@handle
def deploy_keys(request, name):
    g.repo_path(name)  # 404 for a repository that is not yours
    if request.method == "POST":
        return _add(request, repo=name)
    qs = SSHKey.objects.filter(user=request.user, repo=name).order_by("created", "id")
    return Response([sshkeys.as_json(k) for k in qs])


@api_view(["DELETE"])
@handle
def deploy_key(request, name, key_id):
    g.repo_path(name)
    n, _ = SSHKey.objects.filter(pk=key_id, user=request.user, repo=name).delete()
    return Response(status=204) if n else bad("No such key.", 404)
