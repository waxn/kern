# Git access: tokens and public repositories

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
`PATCH /api/git/repos/<name>` accepts `public`.
