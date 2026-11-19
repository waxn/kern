"""Releases (a tag, notes and attached files) for hosted git repositories.

Python API for other features (for example CI publishing build artifacts)::

    from notes import git_releases
    asset = git_releases.attach_file("proj", "v1.2", "app.zip", "/tmp/build/app.zip",
                                     create=True, title="Version 1.2", move=False)
    for release in git_releases.releases_for("proj"):   # newest first, model instances
        ...

``attach_file`` finds the release for the tag (creating a published, non-draft release when
missing and ``create`` is true; the tag must already exist in the repository), copies the file
in (or moves it with ``move=True``) and replaces an asset of the same name. It returns the
:class:`ReleaseAsset`. Problems raise :class:`ReleaseError` (a :class:`GitError`). Call it with
the right user active (``with tenancy.use(uid):``).
"""
import hashlib
import mimetypes
import os
import secrets
import shutil
import subprocess
import unicodedata
from pathlib import Path

from django.db import IntegrityError
from django.utils import timezone

from kern import tenancy

from . import gitrepo as g
from .models_git_releases import Release, ReleaseAsset

DIR = "git-releases"
MAX_FILENAME = 200  # bytes
MAX_ASSETS = 200
TAG_MAX = 200


class ReleaseError(g.GitError):
    pass


def max_file_size() -> int:
    try:
        return max(1, int(os.environ.get("KERN_RELEASE_MAX_BYTES", 2 * 1024**3)))
    except ValueError:
        return 2 * 1024**3


# ------------------------------------------------------------------ storage


def base_dir() -> Path:
    return Path(tenancy.data_dir()) / DIR


def release_dir(repo: str, release_id: int) -> Path:
    return base_dir() / repo / str(int(release_id))


def safe_filename(name: str) -> str:
    """A plain file name: no directories, no control characters, no leading dots, bounded length."""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = name.strip().lstrip(".").strip()
    while len(name.encode()) > MAX_FILENAME:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) < 20 and stem:
            name = stem[:-1] + "." + ext
        else:
            name = name[:-1]
    return name or "file"


def asset_path(asset: ReleaseAsset) -> Path:
    r = asset.release
    return release_dir(r.repo, r.id) / asset.filename


def purge_repo(repo: str) -> None:
    """Delete every release of a repository, with its files."""
    Release.objects.filter(repo=repo).delete()
    shutil.rmtree(base_dir() / repo, ignore_errors=True)


# --------------------------------------------------------------------- tags


def check_tag_name(tag) -> str:
    if not isinstance(tag, str) or not tag or len(tag) > TAG_MAX or tag.startswith("-") or tag != tag.strip():
        raise ReleaseError("Invalid tag name.")
    r = subprocess.run(["git", "check-ref-format", f"refs/tags/{tag}"], capture_output=True, env=g.env())
    if r.returncode != 0:
        raise ReleaseError("Invalid tag name.")
    return tag


def tag_exists(path: Path, tag: str) -> bool:
    r = g.git(path, "rev-parse", "--verify", "--quiet", "--end-of-options", f"refs/tags/{tag}", check=False)
    return bool(r.strip())


def create_tag(path: Path, tag: str, target: str | None) -> str:
    """A lightweight tag at a branch or commit; returns the commit SHA."""
    sha = g.resolve(path, target or None)
    if not sha:
        raise ReleaseError("The repository has no commits to tag.")
    g.git(path, "update-ref", f"refs/tags/{tag}", sha, "")  # "" = it must not exist yet
    return sha


def delete_tag(path: Path, tag: str) -> None:
    g.git(path, "update-ref", "-d", f"refs/tags/{tag}", check=False)


# ----------------------------------------------------------------- releases


def releases_for(repo: str):
    """Releases of a repository, newest first."""
    return Release.objects.filter(repo=repo).order_by("-created", "-id")


def latest(repo: str) -> Release | None:
    return (Release.objects.filter(repo=repo, draft=False, prerelease=False)
            .order_by("-published", "-id").first())


def create_release(repo: str, tag, *, target=None, title="", notes="", draft=False, prerelease=False) -> Release:
    path = g.repo_path(repo)
    tag = check_tag_name(tag)
    if Release.objects.filter(repo=repo, tag=tag).exists():
        raise ReleaseError("There is already a release for that tag.", 409)
    made = False
    if not tag_exists(path, tag):
        create_tag(path, tag, target)
        made = True
    try:
        return Release.objects.create(
            repo=repo, tag=tag, title=str(title or "")[:200], notes=str(notes or ""), draft=bool(draft),
            prerelease=bool(prerelease), published=None if draft else timezone.now())
    except IntegrityError:
        if made:
            delete_tag(path, tag)
        raise ReleaseError("There is already a release for that tag.", 409)


def update_release(release: Release, data: dict) -> Release:
    if "title" in data:
        release.title = str(data["title"] or "")[:200]
    if "notes" in data:
        release.notes = str(data["notes"] or "")
    if "prerelease" in data:
        release.prerelease = bool(data["prerelease"])
    if "draft" in data:
        release.draft = bool(data["draft"])
        if not release.draft and release.published is None:
            release.published = timezone.now()
    release.save()
    return release


def delete_release(release: Release, delete_git_tag=False) -> None:
    repo, tag = release.repo, release.tag
    shutil.rmtree(release_dir(repo, release.id), ignore_errors=True)
    release.delete()
    if delete_git_tag:
        try:
            delete_tag(g.repo_path(repo), tag)
        except g.GitError:
            pass


def store_file(release: Release, filename: str, chunks, *, limit=None) -> ReleaseAsset:
    """Write a stream of byte chunks as an asset (replacing one with the same name). The file is
    streamed to disk, hashed on the way, and refused once it passes the size limit."""
    limit = limit or max_file_size()
    name = safe_filename(filename)
    d = release_dir(release.repo, release.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".upload-{secrets.token_hex(8)}"
    h, size = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise ReleaseError(f"A file may be at most {limit} bytes.", 413)
                h.update(chunk)
                out.write(chunk)
        return _commit_asset(release, name, tmp, size, h.hexdigest())
    finally:
        tmp.unlink(missing_ok=True)


def _commit_asset(release, name, tmp: Path, size, digest) -> ReleaseAsset:
    existing = release.assets.filter(filename=name).first()
    if existing is None and release.assets.count() >= MAX_ASSETS:
        raise ReleaseError("Too many files on this release.")
    ctype = (mimetypes.guess_type(name)[0] or "application/octet-stream")[:100]
    os.replace(tmp, release_dir(release.repo, release.id) / name)
    fields = dict(size=size, sha256=digest, content_type=ctype, downloads=0)
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.save()
        return existing
    return ReleaseAsset.objects.create(release=release, filename=name, **fields)


def delete_asset(asset: ReleaseAsset) -> None:
    asset_path(asset).unlink(missing_ok=True)
    asset.delete()


def attach_file(repo: str, tag: str, filename: str, src_path, *, create=True, title=None, move=False) -> ReleaseAsset:
    """Add a file on disk to the release of ``tag`` (see the module docstring)."""
    release = Release.objects.filter(repo=repo, tag=tag).first()
    if release is None:
        if not create:
            raise ReleaseError("There is no release for that tag.", 404)
        path = g.repo_path(repo)
        check_tag_name(tag)
        if not tag_exists(path, tag):
            raise ReleaseError("There is no such tag in the repository.", 404)
        try:
            release = Release.objects.create(repo=repo, tag=tag, title=title or tag, published=timezone.now())
        except IntegrityError:
            release = Release.objects.get(repo=repo, tag=tag)
    src = Path(src_path)
    if not src.is_file():
        raise ReleaseError("The file to attach does not exist.", 404)
    with open(src, "rb") as f:
        asset = store_file(release, filename or src.name, iter(lambda: f.read(1024 * 1024), b""))
    if move:
        src.unlink(missing_ok=True)
    return asset


# ------------------------------------------------------------ serialisation


def asset_json(a: ReleaseAsset, repo: str) -> dict:
    return {"id": a.id, "filename": a.filename, "size": a.size, "sha256": a.sha256,
            "content_type": a.content_type, "downloads": a.downloads, "created": a.created.isoformat(),
            "url": f"/api/git/repos/{repo}/releases/{a.release_id}/assets/{a.id}/download"}


def release_json(r: Release, tags: set[str] | None) -> dict:
    """``tags``: the names of the repository's tags (None: unknown, so not reported missing)."""
    return {"id": r.id, "repo": r.repo, "tag": r.tag, "title": r.title, "notes": r.notes,
            "draft": r.draft, "prerelease": r.prerelease, "created": r.created.isoformat(),
            "published": r.published.isoformat() if r.published else None,
            "tag_missing": tags is not None and r.tag not in tags,
            "assets": [asset_json(a, r.repo) for a in r.assets.all()]}


def tag_names(repo: str) -> set[str] | None:
    try:
        return {t["name"] for t in g.tags(g.repo_path(repo))}
    except g.GitError:
        return None
