## Git releases

Each repository has a **Releases** tab: a tag with a title, Markdown notes and attached
files, like GitHub Releases. The Code tab shows a quiet line pointing at the latest one.

- **New release**: pick an existing tag, or type a new name and a branch to tag. A new tag is
  a lightweight tag created at that branch's current commit; names git would refuse are
  rejected. There is one release per tag. Mark it **Draft** (not counted as the latest) or
  **Pre-release** (shown with a chip, also not the latest).
- **Files**: drag files onto the form (or click it). They are streamed to disk, so large
  files do not use memory. Uploading a file with the same name replaces it. Names are
  cleaned up (no folders, no leading dots, at most 200 bytes). Each file may be up to 2 GB;
  set `KERN_RELEASE_MAX_BYTES` to change that. The SHA-256 and a download count are kept.
- **Source code** links download the tag's repository as zip or tar.gz.
- **Deleting** a release removes its files; a checkbox also deletes the tag (off by
  default). If a tag is deleted in git, the release stays and shows **Tag missing**.
  Deleting a repository deletes its releases and files.
- Files are stored in `<your data folder>/git-releases/<repo>/<release id>/`, outside the
  git repository. Backups include and restore them.

### API

```
GET/POST  /api/git/repos/<name>/releases                       list (newest first) / create
GET       /api/git/repos/<name>/releases/latest                newest non-draft, non-pre-release
GET/PATCH/DELETE  /api/git/repos/<name>/releases/<id>          (DELETE ?delete_tag=1 also removes the tag)
POST      /api/git/repos/<name>/releases/<id>/assets           multipart, field "files" (one or more)
DELETE    /api/git/repos/<name>/releases/<id>/assets/<asset>
GET       /api/git/repos/<name>/releases/<id>/assets/<asset>/download
```

Create takes `tag`, optional `target` (branch or commit, used when the tag is new), `title`,
`notes`, `draft`, `prerelease`. Downloads are attachments with `nosniff`, a sandboxing
`Content-Security-Policy`, and `Range` support.

### From Python (for example CI publishing build artifacts)

```python
from notes import git_releases
asset = git_releases.attach_file("proj", "v1.2", "app.zip", "/tmp/app.zip", title="1.2", move=True)
```

Creates a published release for the (existing) tag if needed, copies or moves the file in and
replaces an asset with the same name. `git_releases.releases_for(repo)` lists releases.
