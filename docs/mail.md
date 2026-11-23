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
- **New mail arrives in about a second.** The worker holds an IMAP IDLE connection on the
  Inbox; when the server reports new mail it fetches just that (pushed mail jumps ahead of a
  folder sweep that's in progress). The browser long-polls `/api/mail/changes?wait=20`: the
  request is held until the worker stores something, then the list refreshes. The refresh
  button asks the worker to check the mail server right away (`POST /api/mail/check`).
- **The Inbox opens instantly.** `ThreadFolder` is a small per-folder index of conversations
  (newest first, with an unread flag), kept up to date by `threads.refresh_thread()`, so a
  folder's list and counts are an index read instead of a scan of every message. The browser
  also keeps the last folder list and first page of each view on this device (cleared on sign
  out) and shows them while the fresh copy loads. `threads.rebuild_thread_index()` rebuilds the
  index if it ever needs repairing.
- **Mail and Notes are two modes** (the switch at the top of the sidebar, Alt+M). Each has its
  own sidebar with the same top (hide-sidebar, Kern, the switch, then Search, New and Home on the
  same rows), so switching moves nothing; Home, Settings and Intelligence belong to both.
- **Intelligence on an email** (the sparkle in a conversation): the assistant gets that
  conversation's text without asking (you picked it), marked as untrusted data, from a two-factor
  session only. It can make tasks, pages and flashcards from it; it has no way to send,
  move or delete mail.
- **Emails sit on Kern's background.** The server fits each HTML email's colors to the theme
  (`backend/mail/colors.py`): white and grey "pages" become transparent so the email reads on the
  same background as the rest of the app, and in the dark theme light backgrounds are darkened and
  dark text lightened, keeping their hues (pictures are untouched; nothing is inverted). Mail that's
  dark already keeps its colors (only its black page goes), and mail with its own dark mode
  (`prefers-color-scheme`) uses it. The sun button on a message shows its original colors.
  Settings → Mail → Fit emails to the theme turns it off. Web and Android get the same result.
- **Kern Mail for Android** (`android/`, the `mail` flavor) is a mail-only app with instant
  notifications: a foreground service long-polls the same feed (holds of 50 s growing to about
  4.5 min when nothing on the way cuts them short), so there's no Firebase. Notifications show
  sender and subject (only "New mail" on the lock screen) with Archive and Mark read.
- **Search** (the sidebar's Search row, Ctrl+K or `/`, in the same place as Notes' search) shows
  results while you type: people (Tab completes `from:`), labels, folders and the best
  conversations with the words that matched. Enter shows every result, newest first or best
  match first (bm25, recent mail boosted), with filter chips. It uses SQLite FTS5 (subject, people,
  attachment names, body; every word matches as a prefix, accents folded) plus operators: `from:`
  (`from:me`) `to:` (`to:me`) `cc:` `subject:` `domain:` `list:` `in:` `label:`
  `has:attachment|pdf|image|document|spreadsheet|presentation|calendar|link` `is:unread|read|starred|
  answered|snoozed|muted` `before:` `after:` `older_than:2w` `newer_than:3d` `larger:5M` `smaller:100K`
  `filename:` `risk:high` `"exact words"` `-word` `a OR b`.
- **Tasks.** `t` (or the ✓ button) on a conversation makes a Kern task that links back to the
  email. "Nudge me if nobody replies" also creates a task due on that day; a reply completes it,
  completing or deleting the task ends the nudge, and moving the task's date moves the nudge.
  Home shows unread mail, nudges, snoozed mail coming back today, packages arriving today and
  scheduled sends.
- **Packages** are detected from shipping emails by rules (tracking-number formats with check
  digits, status words) and shown small at the top of the Inbox and on the Packages page (web and
  Android). **Live tracking** (opt-in, Settings → Mail → Package tracking) asks a tracking
  service for the carrier's real status about every 90 minutes (25 on delivery day) from the mail
  worker (`backend/mail/tracking.py`, services in `backend/mail/trackers/`):
  - **Universal Parcel Scraper** (Peek's open-source engine) reads each carrier's own site with
    no account or key. It's built into Kern's Docker image (Node plus the npm package, pinned in
    `backend/Dockerfile`; the mail worker runs it per lookup, in a thread of its own so slow
    carriers never hold up mail). USPS, FedEx, Royal Mail and other carriers only answer a real
    browser session; Kern runs no browser service, so use Parcels or TrackingMore for those. Or point Kern at a
    scraper you run (`parcel-scraper serve`). When a lookup finds nothing, the package says why.
    Amazon Logistics can't be tracked live. Fallback trackers (UPU on by default; ParcelsApp, Ship24, 17TRACK… opt-in) each
    receive the number. Licence: Apache-2.0 up to 0.1293.2 (the pinned version), PolyForm
    Noncommercial after.
  - **Parcels** (parcelsapp.com, API v5): API key, free for 300 packages a month.
  - **TrackingMore** (trackingmore.com, API v4): API key, one credit when a package is added,
    free re-checks.
  For metered services Kern counts each package once a month (as they bill) and shows what's left
  next to the key, using the service's own figures when it reports them. Only tracking numbers,
  and your country for numbers that need one, are sent.
- A **map** on the Packages page shows every package at once (click a name to jump to its card),
  and each package's card has its own. It draws a line through the scans (places looked up once with
  OpenStreetMap's Nominatim, `backend/mail/geo.py`) on tiles the server fetches and caches, so the
  browser never contacts the map service. Sources (Settings → Mail → Package map): OpenStreetMap
  (no key, toned to the theme), Esri's grey canvas (no key, dark and light), MapTiler, Stadia Maps,
  Thunderforest or Mapbox (free keys, dark and light styles), or your own tile server. Without
  live tracking, a package with no news two days after it was due counts as "probably delivered".
- **Send mail as** (Settings → Mail): other addresses you send from, e.g. a Gmail that forwards to
  this mailbox. With the address's own SMTP server (Gmail: smtp.gmail.com, an app password) mail
  goes out through it and one copy is saved in Sent here; replies default to the address the
  email was written to (`backend/mail/identities.py`).
- **Stats** (`/mail/stats`): received and sent per day, time of day, weekdays, read rate, typical
  reply time, newsletters, top senders and domains, mailbox size.
- **Intelligence** asks before reading mail: searching, opening an email or a conversation
  (`read_email_thread`) and a message's full headers (`read_email_headers`) show a permission
  request first. The exception is "Ask about this email", where picking the conversation is the OK.
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
- Desktop notifications say only "New mail", never the sender or subject (Android shows them
  only when unlocked, if you allow it). A conversation read anywhere else takes its Android
  notification away within about a second.
- **Live package tracking** sends tracking numbers (and your country) to the service you pick,
  only after you turn it on: the carriers themselves (built-in scraper, plus any fallback you
  tick), Parcels or TrackingMore. Keys and tokens are encrypted like mail passwords; a scraper or
  tile server you point Kern at must be public unless an administrator allows local servers. The
  map sends scan place names to Nominatim and fetches tiles from the chosen source, from the
  server only. **Send-as** passwords are too, and their SMTP
  hosts must be public like the account's.

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
