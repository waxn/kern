# Git access: tokens, passwords and public repositories

## Renaming a repository

**Settings → Repository name** renames it. The clone URLs change with it, so point existing
clones at the new one (`git remote set-url origin <new URL>`); the old URL stops working and the
old name is free for a new repository. Everything keyed by the name moves along: access tokens,
the repository password, deploy keys, protected branches, releases and their files, webhooks,
push mirrors, CI runs and secrets. A rename is refused while a CI job is running.

## Owner URLs

Besides `http://<server>/git/<name>.git` (which always asks you to sign in as the owner),
a repository can be reached at `http://<server>/git/<username>/<name>.git`. This form is what
anonymous clones and access tokens use. The user name is matched case-insensitively and only
active accounts resolve.

## Public repositories

**Git → repository → Settings → Access → Public** lets anyone clone and fetch the repository at
its owner URL without signing in. Pushing always needs credentials. Turning it off, or turning
git hosting off for the server, closes it again. The repository's clone box shows the owner URL
while it is public. Private repositories answer anonymous requests with a sign-in challenge,
whether or not they exist.

## Repository password

**Settings → Access → Password** sets a password of your choosing for one repository. Anyone who
knows it can clone and fetch at the owner URL with any user name; git asks for it like any
other password:

```bash
git clone http://<server>/git/alice/my-project.git
```

- Read-only: a push with it gets `403`. Push with your account or a write token.
- It works for that one repository only, and never on the legacy `/git/<name>.git` URL.
- Minimum 8 characters. Changing it locks out anyone using the old one; **Remove** turns it off.
- It is stored as a salted hash (Django's password hasher) in the repository's `kern.json`, and
  the API only reports `has_pull_password`.
- Wrong guesses are rate limited per repository (30) and per address, like token attempts.

This is separate from the account-wide git password on the Git page, which signs in as you
(read and write, every repository).

## Access tokens

Create tokens under **Settings → Access**: a label, a scope (**read** to clone and fetch, **write**
to also push) and an expiry (never, 30 days, 90 days, 1 year). The token is shown once; copy it
then. Use it as the HTTP password with any user name, on the owner URL:

```bash
git clone http://x:kern_12_abc...@<server>/git/alice/my-project.git
```

- A token works for one repository of one owner only, never the legacy URL.
- A read token trying to push gets `403` with a message saying it is read-only.
- Expired or revoked tokens stop working at once; deleting a repository (or an account) revokes
  its tokens. Last-used time is shown in the list.
- Failed attempts are rate limited per token and per address, like password sign-ins.
- Pushes made with a token are attributed to `token:<label>`.
- Tokens are stored as `kern_<id>_<secret>` rows in the shared database (owner id, repository,
  scope, SHA-256 of the secret), so a token finds its owner without scanning every user. They are
  not part of backups.

API: `GET/POST /api/git/repos/<name>/tokens`, `DELETE /api/git/repos/<name>/tokens/<id>`;
`PATCH /api/git/repos/<name>` accepts `name` (rename), `public` and `pull_password` (empty to remove).
