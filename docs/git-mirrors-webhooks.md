# Git push mirrors and webhooks

Both live in a repository's **Settings** tab.

## Push mirrors

After every push, Kern copies the repository's branches and tags to another remote, for example a
GitHub repository, so GitHub Actions can run there too. You can add several mirrors per repository.

- **URL**: `https://...` with no credentials in it. Enter the **username** and **token/password**
  in their own fields (for GitHub: your username and a personal access token with `repo` scope).
  The token is stored encrypted (`kern.secretbox`) and is never returned by the API.
- **What is pushed**: `git push --porcelain --prune <url> +refs/heads/*:refs/heads/* +refs/tags/*:refs/tags/*`.
  This is used instead of `--mirror` because `--mirror` also pushes every other ref, which hosts such
  as GitHub reject. Branches and tags are force-updated, and ones deleted in Kern are deleted on the
  remote. A repository with no branches or tags is never pushed, so a mirror can't wipe a remote.
- **Filters**: "only protected branches" and/or a list of branch patterns (`main release/*`). With a
  filter only the matching branches are pushed (and branch deletions are not propagated); tags are
  always mirrored.
- **How the token travels**: in the git process's environment as an `http.extraHeader`
  `Authorization` header, never in argv, the URL or the repository config. It is scrubbed from the
  stored error text. Redirects are not followed.
- **Status**: last attempt, last success and last error are shown. A sync that is already running
  is not duplicated: pushes that arrive meanwhile cause exactly one more run afterwards.
  "Sync now" runs it on demand.

## Private addresses

Mirror and webhook hosts must resolve only to public addresses. An administrator can allow
private, loopback and link-local destinations under **Settings -> Server -> Git mirrors and webhooks
on the local network** (`allow_local_git_remotes`, off by default). Plain `http://` is accepted for
mirrors only to such local addresses. The check runs when you save and again before each connection;
mirrors also pin git to the checked addresses.

## Webhooks

Kern sends a `POST` with a JSON body when an event happens. URL (http or https, no credentials),
optional secret (stored encrypted) and the events to send are set per hook. Events today: `push`
(one delivery per push, with all ref updates). **Send test** sends a `ping`.

Request headers:

| Header | Value |
| --- | --- |
| `Content-Type` | `application/json` |
| `User-Agent` | `Kern-Hookshot` |
| `X-Kern-Event` | `push`, `ping`, ... |
| `X-Kern-Delivery` | a UUID, new for every delivery (and every redelivery) |
| `X-Kern-Signature-256` | `sha256=<hex>`, only when the hook has a secret |

Push payload:

```json
{
  "event": "push",
  "repository": { "name": "notes", "owner": "ada" },
  "pusher": "ada",
  "via": "http",
  "refs": [
    {
      "ref": "refs/heads/main",
      "before": "0000000000000000000000000000000000000000",
      "after": "3f2c...",
      "created": true,
      "deleted": false,
      "commits": [{ "sha": "3f2c...", "subject": "Add readme", "author": "Ada", "date": "2026-01-02T10:00:00+00:00" }]
    }
  ],
  "timestamp": "2026-01-02T10:00:01+00:00"
}
```

`commits` is `git log before..after`, at most 20 per ref (empty for deleted refs; for a new ref,
only commits no other branch or tag already had). At most 50 refs are listed (`refs_truncated`
says how many were left out). `ping` carries `zen` and `hook_id` instead of `refs`.

### Verifying the signature

Compute the HMAC-SHA256 of the **raw request body** with the secret and compare in constant time:

```python
import hashlib, hmac

def verify(secret: bytes, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

### Delivery behaviour

10 second timeout, redirects are **not** followed (a 3xx counts as a failure), network errors and 5xx
answers are retried twice (after 1 s and 4 s), 4xx answers are not. Each hook keeps its last 30
deliveries with status, duration, error, the request (headers and body) and the first 4000
characters of the response. **Redeliver** sends a stored request again with a new delivery id.

## For other features: `emit`

```python
from notes import gitwebhooks

gitwebhooks.register_event("release", "Release published")   # once, at import: makes it selectable in the UI
gitwebhooks.emit(owner_uid, "repo-name", "release", {"tag": "v1.0"})
```

`emit(owner_uid, repo, event, payload)` delivers to the repository's enabled hooks subscribed to
`event` (each on its own thread; synchronously under `KERN_TESTING`) and returns how many hooks
were notified. `payload` is a dict, or a function returning one (called only if some hook is
subscribed). Kern adds `event`, `repository` and `timestamp`. It never raises.

## API

Under `/api/git/repos/<name>/`: `mirrors` (GET, POST), `mirrors/<id>` (PATCH, DELETE),
`mirrors/<id>/sync` (POST); `webhooks` (GET, POST), `webhooks/<id>` (PATCH, DELETE),
`webhooks/<id>/test` (POST), `webhooks/<id>/deliveries` (GET), `webhooks/<id>/deliveries/<did>` (GET,
with bodies), `webhooks/<id>/deliveries/<did>/redeliver` (POST). Send `secret` to set a secret and
`clear_secret: true` to remove it; responses only contain `has_secret`.
