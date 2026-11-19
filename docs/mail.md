# Mail

Kern can read and send your email. Each user connects their own mailbox (any IMAP/SMTP
provider) in **Settings → Mail**, and gets a mail client inside Kern: conversations, fast
search, folders and labels, snooze, follow-up nudges, send later, reply templates, package
tracking, phishing warnings, spam reporting with sender/domain blocking, and a list of every
attachment. Mail is in the web app (`/mail`, sidebar → Mail, `Alt M`) and in the Android app
(More → Mail).

Mail started as a separate project (Manifest) and was merged in; the engine lives in
`backend/mail/` and the web UI in `frontend/src/lib/mail/`.

## Setting it up

1. **Two-factor sign-in first.** Settings → Account → Two-factor sign-in: scan the QR code with
   an authenticator app (Aegis, 2FAS, 1Password, Bitwarden…), enter a code, save the recovery
   codes. Mail can't be opened without it (see Security below). Turning it on signs out your
   other devices; sign in again there with a code.
2. **Connect.** Settings → Mail: pick your provider (Purelymail, Fastmail, Gmail, iCloud) or
   Other, enter the address and password (an *app password* for Gmail, Fastmail and iCloud),
   **Test**, then **Connect**. The first download of a big mailbox takes a while; the sidebar
   shows progress.
3. The `mail` service in `docker-compose.yml` does the syncing. `docker compose up -d --build`
   starts it with the rest; `docker compose logs mail` shows what it's doing.

Administrators: Settings → Server has **Mail** (on/off for the whole server) and **Mail servers
on the local network** (off by default, see Security).

## How it works

- **The mail server is the source of truth.** A local copy (in your own database, raw
  messages in `users/<id>/mail/`) makes the app and search fast. Changes you make here are
  applied locally at once and written back to the server by the mail service; changes made
  elsewhere (your phone's mail app) come in through IMAP IDLE (Inbox, instantly) and periodic
  checks of the other folders.
- **One worker per mailbox.** `manage.py mail_worker` runs a supervisor that keeps one sync
  thread per connected account, each running as that user, and restarts it when the account's
  settings change. Without Docker, run it next to `runserver`.
- **Live updates** in the browser: the page polls `/api/mail/changes` every few seconds while
  visible (Kern is served by threaded WSGI, so there's no held-open event stream).
- **Search** uses SQLite FTS5 (subject, people, attachment names, body) plus Gmail-style
  operators: `from:` `to:` `subject:` `in:` `label:` `has:attachment` `is:unread` `before:`
  `after:` `filename:` `"exact words"` `-word`.
- **Tasks.** `t` (or the ✓ button) on a conversation makes a Kern task that links back to the
  email. "Nudge me if nobody replies" also creates a task due on that day; a reply completes it,
  completing or deleting the task ends the nudge, and moving the task's date moves the nudge.
  Home shows unread mail, nudges, snoozed mail coming back today, packages arriving today and
  scheduled sends.
- **Packages** are detected from shipping emails by rules (tracking-number formats with check
  digits, status words). Kern never contacts a carrier; "Track" is just a link.
- **Backups** (Settings → Data & backups) keep your mail *settings and the things you made*
  (snoozes, follow-ups, templates, block rules, labels) but leave the downloaded messages out:
  they're on the mail server, and email content shouldn't spread to every backup copy.
  Restoring clears the local copy and downloads it again. A password saved on another server
  can't be decrypted here (different key), so you enter it again.

## Security

Mail makes Kern a much more valuable target, so these are deliberate:

- **Two-factor sign-in is required for mail.** `/api/mail` refuses a session unless the account
  has an authenticator set up *and* this session passed the second step
  (`backend/mail/api/guard.py`). A stolen password, or a browser that signed in before 2FA was
  turned on, never reaches a mailbox. With 2FA on, git over HTTP accepts only the separate git
  password (git clients can't send a code). You can't turn 2FA off while mail is connected.
- **TOTP codes** can't be replayed (the last used 30-second step is stored), wrong codes are
  rate limited like passwords, recovery codes are single use and stored hashed.
- **Secrets at rest.** Mail passwords and TOTP seeds are encrypted (Fernet) with a key that's a
  file outside every database: `DATA_DIR/secrets/kern.key`, created on first use with mode 0600,
  or the file named by `KERN_SECRET_BOX_KEY_FILE` (e.g. a Docker secret). A copy of a database
  or a backup zip alone doesn't reveal them. The password is write-only: the browser is only
  told whether one is stored.
- **Email HTML is untrusted.** It's cleaned on the server with an allowlist sanitizer
  (`backend/mail/sanitize.py`: no scripts, event handlers, forms, frames, `javascript:` URLs or
  dangerous CSS) and then shown in a sandboxed iframe that may never run scripts, with its own
  Content-Security-Policy (`frontend/src/lib/mail/emailFrame.js`). The Android app shows it in
  a WebView with JavaScript off and all network and file access blocked.
- **Remote images and trackers are blocked** until you click "Load images" (or trust the
  sender). They then load through Kern's image proxy, which signs each URL, refuses private
  and local addresses and pins the address it checked, so senders never see your IP address or
  browser and can't use Kern to reach your network.
- **Attachments** are served with `Content-Disposition: attachment`, a sandbox CSP and nosniff;
  only plain raster images (PNG, JPEG, GIF, WebP) are ever shown inline.
- **Mail servers must be public.** Users type in IMAP/SMTP hosts and the server connects to
  them, so hosts that resolve to private, loopback or link-local addresses are refused
  (`backend/mail/hosts.py`), at save time and again at every connect. An administrator can
  allow local mail servers in Settings → Server.
- **Per-user isolation** is Kern's: mail tables live only in each user's own database. The few
  in-memory caches the mail engine keeps (contacts for the phishing rules, worker status) are
  keyed by user.
- **Phishing checks** are rules only (`backend/mail/risk/rules.py`, weights in `rules.yaml`):
  sender/display-name tricks, look-alike domains, link targets, attachment names, and
  Authentication-Results headers, which are only trusted when they carry your provider's
  authserv-id (Settings → Mail → More options). No message content leaves the server; nothing
  is sent to an AI provider.
- **One-click unsubscribe** (RFC 8058) is only offered for DKIM-verified senders and goes
  through the same public-address check as the image proxy.
- Desktop and Android notifications say only "New mail", never the sender or subject.

**Read carefully** if you review the code: `backend/mail/sanitize.py`,
`frontend/src/lib/mail/emailFrame.js`, `backend/mail/api/guard.py`, `backend/accounts/totp.py`,
`backend/kern/secretbox.py`, `backend/mail/hosts.py`, `backend/mail/imgproxy.py`,
`backend/mail/api/views_account.py`, and the `EmailView` WebView in
`android/app/src/main/java/app/kern/ui/screens/MailScreens.kt`.

## Development

```bash
cd backend
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python manage.py mail_worker          # sync every connected mailbox
.venv/bin/python manage.py demo --user alice    # or: a demo mailbox for one user, no mail server
KERN_TESTING=1 .venv/bin/python -m pytest       # mail tests (the rest: manage.py test)
```

`demo` fills an in-memory mailbox with a messy test corpus (broken encodings, hostile HTML,
phishing, duplicate Message-IDs, a 200-message thread, shipping emails) and syncs it as that
user. The user still needs two-factor sign-in to open it.

Frontend: `cd frontend && npm test` runs the mail helpers' unit tests.

## Not included

- Calendar invites are shown as attachments, not as events.
- The Android app reads, sorts and writes plain-text mail; images from the web, attachments
  downloads, labels and settings are in the web app.
- One mailbox per Kern user.
