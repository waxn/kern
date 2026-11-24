# Kern for Android

A native Android client for a Kern server: Kotlin, Jetpack Compose (Material 3), the same
colours and Inter typeface as the web app, light and dark themes. It talks to the normal
`/api` with the same session cookie a browser uses, so nothing changes on the server.

Two apps are built from this code (Gradle product flavors):

- **Kern** (`kern`, `app.kern`): everything below.
- **Kern Mail** (`mail`, `app.kern.mail`): mail only, with its own icon and instant
  notifications. Tasks, pages and flashcards you make from an email (by hand or with
  Intelligence) are saved to Kern; opening one hands over to the Kern app, or to the web app
  when Kern isn't installed. With Kern Mail installed, Kern leaves mail notifications to it.

## Build

Needs JDK 17 and the Android SDK (platform 35, build-tools 35).

```bash
cd android
./gradlew assembleDebug           # app/build/outputs/apk/{kern,mail}/debug/app-*-debug.apk
./gradlew assembleRelease         # minified, app/build/outputs/apk/{kern,mail}/release/
./gradlew assembleMailRelease     # just Kern Mail
./gradlew testKernDebugUnitTest   # HTML ↔ markup and quick-add parser tests
```

### Kern Mail's instant notifications

New mail shows within a second or two without Google's push service: a foreground service
keeps one long-poll request open to your Kern server (`/api/mail/changes?wait=…`), which answers
as soon as the mail worker (IMAP IDLE) stores a message. Each hold starts at 50 seconds and
doubles up to about 4.5 minutes while nothing between the phone and the server (a proxy's
timeout, a NAT) cuts requests short, so the radio wakes rarely. Android requires a notice while
the service runs; it uses a silent "Connection" channel you can turn off by long-pressing it.
Settings in the app turn instant notifications off (a 15-minute check stays as a backstop) or
hide the sender and subject; the lock screen only ever shows "New mail". Package updates,
snoozed mail coming back and "No reply yet" reminders arrive the same way, with the web app's
titles, on their own "Packages and reminders" channel. Behind nginx, raise
`proxy_read_timeout` above 300 s (Caddy has no limit by default); otherwise the app settles on
shorter holds by itself.

The release build is signed with the debug key so it installs straight away; set up your
own `signingConfig` in `app/build.gradle.kts` before distributing it.

GitHub Actions (`.github/workflows/android.yml`) runs the tests and builds both APKs on every
push to `main` that touches `android/`; download them from the run's **kern-android** artifact.
Push a tag such as `android-v1.0` to also attach the APKs to a GitHub release.

Install on a phone with `adb install app/build/outputs/apk/release/app-release.apk`, then
enter the address you open Kern at (for example `http://192.168.1.20:8420`). Plain HTTP is
allowed because Kern is usually self-hosted on a home network; use HTTPS when it is exposed.

## What's in it

- **Sign in / sign up** (approval-pending and setup-needed servers are handled; the first-run
  setup wizard stays in the browser), with the two-factor code step when it's on.
- **Mail** (More → Mail): the web app's list (day headings, All | Unread, stars; swipe right to
  archive, left to snooze with the web's choices, long-press for more), search, full-width
  conversations (email HTML in a WebView with JavaScript and file access off that loads only
  pictures from your Kern server: inline images, and remote ones through its image proxy after
  "Load images"), attachments that open in other apps, archive, trash, star, mark unread, report
  spam, make a task, reply/reply all/forward and new messages (plain text, with your signature).
  A "New mail" notification (never the sender or subject), a Mail card on Home, and tasks made
  from an email open it. Connecting the account and two-factor setup are in the web app.
- **Home**: greeting, today's tasks, flashcards due, favorites, recently edited.
- **Pages**: the page tree (expand, long-press for sub-page, favorite, rename, duplicate,
  archive, trash), favorites, databases; new page, group, database, kanban, calendar or
  from a template.
- **Editor**: every block type renders (headings, lists, checklists, toggles, quotes, callouts,
  code, equations, tables, images, files, bookmarks, embeds, synced and database blocks).
  Text blocks are editable with a formatting bar: block type, checklist, bold, italic, strike,
  code, highlight, links, `[[page]]` links and `#tags` (new ones are created), indent/outdent,
  move, delete. Markdown shortcuts (`- `, `1. `, `[] `, `# `, `> `, ```` ``` ````, `---`), Enter splits
  and continues lists, Backspace at the start merges. Edits autosave with the server's
  conflict check. Page icon, title, tags, properties, backlinks, card and task badges.
- **Databases**: board (long-press a card to move it), calendar, gallery and list views with
  the views' saved filters and sorts; new entries.
- **Tasks**: Today / Upcoming / Inbox / All / Done, quick add with the web's syntax
  (`Pay rent tomorrow !2 #home every month`), detail sheet (notes, due date, priority,
  repeat, tags, delete).
- **Flashcards**: stats, 14-day forecast, 26-week heatmap, decks, study a deck or a page,
  basic / both-ways / cloze / image-occlusion cards, FSRS buttons with intervals, undo,
  new cards.
- **Intelligence**: chats with action links and sources; ask about the open page.
- **Bookmarks**: list, filter, add, read the saved offline snapshot, play/download videos,
  notes and to-dos. **Share** any link or text to Kern from another app to save it as a
  bookmark, page or task.
- **Search** across pages, blocks, tags, cards and tasks, with highlights and recent searches.
- **Tags, Files, Git** (repositories, file browser, commits, README, code view),
  **Templates, Archive, Trash**.
- **Stats** (Settings → Your numbers, the More tab, or the chart icon on Cards): flashcard
  streaks, reviews per day, accuracy, a 26-week heatmap, the 30-day due forecast, card states,
  memory strength (FSRS stability), when you study and the hardest cards; task completions,
  on-time rate, time to finish and open tasks by priority and date; workspace counts, pages
  created per month, storage by kind, files, bookmarks, tags and repositories. Tap a bar or a
  heatmap day to read its exact value.
- **Settings**: theme, text size, reminders, widgets, password, user approval for admins.

### Notifications

A background job runs about every 15 minutes. Settings → Reminders controls it:

- **Flashcards:** while cards are waiting, a reminder with **Review now** and **Later**, repeated
  every hour, 1½, 2, 3 or 4 hours (or once a day). Studying restarts the wait. Choose a minimum
  number of waiting cards, whether new cards count, and how long **Later** holds off.
- **Tasks:** once a day, tasks due today (and overdue ones, if you like), each with **Done** and
  **Tomorrow**; optionally only medium or high priority.
- **Schedule:** start time, quiet hour, and which days of the week.

The Reminders screen also has a test button and a shortcut to Android's sound and vibration
settings for Kern.

### Widgets

- **Today**: open tasks; tap the circle to complete one.
- **Review**: cards due and new.
- **Capture**: search, new page, new task, new bookmark.
- **Pages**: favorites and recent pages.

Add them from Settings → Home screen widgets, or the launcher's widget picker. Long-pressing
the app icon offers New page, New task, Review cards and Search.

### Not in the app (use the web app)

Server and AI provider settings, import/export, backups, the knowledge graph, version
history, PDF annotation, the image-occlusion editor, table cell editing, database schema and
view editing, and git diffs/stats.

## Layout

```
app/src/main/java/app/kern/
  data/       API client (OkHttp, persisted session cookie), models, HTML ↔ markup, quick-add parser
  ui/         navigation, workspace state, theme, shared components
  ui/doc/     page editor, block rendering, database views
  ui/screens/ every other screen
  notify/     reminders worker, notification actions
  widget/     Glance home-screen widgets
```
