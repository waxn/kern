# Kern

A self-hosted, multi-user knowledge base: an outliner-style block editor with
linked pages, tags with properties, Notion-style relational databases, templates,
transclusion and a knowledge graph. Django + DRF + SQLite (FTS5) on the backend,
Svelte 5 / SvelteKit on the frontend, all in Docker.

## Run it

```bash
docker compose up -d --build
```

Then open `http://<your server>:8420` (the port is `KERN_PORT`; pick an unusual
one in `.env`). The first visit shows the **setup wizard**:

1. **Setup code**: printed in the server log, so only someone with access to the
   server can claim it: `docker compose logs backend`.
2. **Administrator**: your username and password.
3. **Access**: whether people can sign up (invite only / approve each / open),
   and whether visitors who are not signed in see a **public landing page** at `/`
   or go straight to the sign-in form.
4. **Server name** and whether git hosting is on.

Everything chosen there can be changed later under **Settings → Server**; add,
approve, disable and remove accounts under **Settings → Users**.

**Moving to a new server, or starting over:** on the second step of the wizard choose
**Restore from a backup** and upload a backup from Settings → Data & backups. It recreates
the account it was made with (same username and password) and, if that account was an
administrator, the server settings, then restores the whole workspace. Backups made before
this existed have no account in them; the wizard then asks for a username and password.
Other people's accounts are not part of your backup: each user restores their own after
signing up.

- Data lives in the `kern_data` Docker volume and survives rebuilds,
  `docker compose down` and updates. Only `docker compose down -v` deletes it.
- Kern listens on `0.0.0.0` by default so you can reach it on a server. Set
  `KERN_BIND=127.0.0.1` in `.env` to keep it on the machine, for example behind a
  reverse proxy. Kern itself speaks plain HTTP: put it behind HTTPS (Caddy, nginx,
  Traefik, a tunnel) and set `KERN_HTTPS=1` so the session cookie is `Secure`.
- Update: `git pull && docker compose up -d --build`. Database migrations run
  automatically when the backend starts.
- **Upgrading from a version without accounts:** the first administrator you create
  takes over the existing notes, files and repositories, so nothing is lost.

### Accounts and privacy

Every user gets a completely separate workspace: `/data/users/<id>/` holds their own
SQLite database, uploaded files, git repositories and backups, and the app only ever
opens the folder of the signed-in user. There is no shared notes table to filter,
so a bug cannot leak one person's pages to another. Administrators manage accounts but
cannot read anyone's pages through the app.

- Passwords are hashed (PBKDF2), at least 10 characters, and checked against common
  passwords. Repeated failures lock a username (and an address) for 15 minutes.
- Sessions use an HTTP-only, `SameSite=Lax` cookie. Writes need an `X-Kern` header
  and are refused when the browser says they come from another site.
- Uploaded files (`/media/…`) are served by the backend after checking the session,
  from the signed-in user's own folder, never straight from disk.
- Changing a password signs out every other device. Signing out clears the offline copies this
  browser kept.
- Backend: `KERN_SETUP_CODE` sets the setup code yourself instead of a random one.

### Backups

Settings → Data & backups creates a backup of **your** workspace, restores one, and keeps an
automatic daily backup (the last 7) inside the data volume. A backup is one
`.zip` with everything: pages, databases, cards, tasks, uploaded files and
their versions, bookmarks and their saved pages, git repositories, and
settings (including the AI key), and your account: username, email and password hash,
plus the server settings for administrators — so keep backups private. Videos downloaded
for bookmarks are left out unless you turn on "Include downloaded videos",
since they are large and can be downloaded again. Restoring always saves a
safety copy first; restoring a backup without videos keeps the videos you have. To copy
backups off the machine:

```bash
docker compose cp backend:/data/users ./kern-users   # each user's backups/ folder is inside
```

### Git server

Kern can host git repositories. Open **Git** in the sidebar, create a
repository, then push to it from any git client:

```bash
git remote add kern http://<your server>:8420/git/my-project.git
git push -u kern main
git clone http://<your server>:8420/git/my-project.git
```

The Git page lists your repositories (size, last push, clone URL); each
repository has a file browser for any branch, tag or commit with a rendered
README, the commit log, single-commit diffs, branches and tags, and a Stats tab
(contribution heatmap, commits per month, when commits happen, languages, top
contributors, totals).

- Repositories are bare repos in your folder of the data volume
  (`/data/users/<id>/git/<name>.git`). They are included in your backups
  (Settings → Data & backups).
- Clone, fetch and push use git's smart HTTP protocol (`git http-backend`) and always
  need a login: your Kern username with your account password, or a separate
  git password you set under **Git → Sign-in** (so your account password never ends up
  in a git credential helper). Administrators can turn git hosting off for the whole
  server in Settings → Server.
- Repository names: letters, digits, `.`, `-`, `_`, up to 64 characters. Server-side
  hooks are disabled and pushed objects are checked (`receive.fsckObjects`).

### Bookmarks

**Bookmarks** in the sidebar saves web pages, images and videos from a URL.

- Web pages are saved as a full snapshot: the page with its stylesheets, images
  and web fonts stored locally (`media/web-pages/<id>/` in your folder), so it looks like
  the real page and still opens when the site changes or goes away. Scripts,
  frames and embeds are removed, and the snapshot is shown sandboxed with a
  policy that blocks scripts and every request to the internet. Use the refresh
  button on a bookmark to re-capture it.
- Videos (YouTube, Vimeo, …) play in place from the site, or can be downloaded
  with yt-dlp (video or audio only, a chosen quality) with live progress.
  YouTube downloads need a JavaScript runtime; the Docker image includes Deno.

## Android app

`android/` holds a native Android client (Kotlin, Jetpack Compose) with the same look as the
web app: pages and the block editor, databases, tasks, flashcard review, Intelligence,
bookmarks, search, git browsing, a Stats screen with charts, plus reminders for due tasks
and cards (repeating card reminders with a cooldown, quiet hours, weekdays and filters under
Settings → Reminders), home-screen widgets and a share target. Build it with `cd android && ./gradlew assembleRelease`; see
[android/README.md](android/README.md).

## What is implemented

**Priority 1 — core knowledge management**
- Sidebar with nested pages (drag to reorder/nest, rename, favorite, archive,
  trash), favorites, recent pages, databases, tabs, global search (`Ctrl/⌘ K`).
- Block editor: paragraphs, headings, bulleted/numbered/to-do/toggle lists,
  quotes, callouts, dividers, code, equations (KaTeX), tables, images, video,
  audio, files, bookmarks. Arbitrary nesting, indent/outdent, drag and drop,
  collapse, multi-select, copy/paste (including Markdown and HTML), duplicate,
  convert, slash menu, Markdown shortcuts, inline formatting, undo/redo,
  autosave with save-state indicator.
- Focus mode: the expand button in a page's top bar hides the sidebar, tabs
  and right panel for distraction-free writing; Esc brings them back.
- `[[` page links, `((` block references, `#` tags, backlinks with context.
- Tags as first-class objects with their own property definitions; per-page
  properties (text, number, checkbox, date, URL, select, multi-select,
  relation, rating).
- Full-text search across pages, blocks, tags and property values with
  highlighting and type filters.

**Priority 2 — advanced organization**
- Databases, full-page or inline in any page. Entries are pages.
- Property types: title, text, number (with formats), checkbox, date, URL,
  email, phone, select, multi-select, status, relation (one- or two-way, across
  databases), rollup, formula, created time, last edited time.
- Views: table (editable cells, resizable columns, row selection, quick entry),
  board (drag cards between groups, collapsible groups), calendar (month/week,
  drag to reschedule, create on a day), gallery (card sizes, covers) and list.
  Each view saves its own filters (nested AND/OR groups), multi-level sorts,
  grouping and visible properties.
- Formula language: `prop("Name")`, arithmetic, comparisons, `and/or/not`,
  `if`, `cond ? a : b` and functions for text, numbers and dates (see the
  reference inside the formula editor).
- Templates for pages and database entries (title, icon, tags, properties,
  nested blocks); tag-bound templates insert their structure when the tag is
  applied. Any page can be saved as a template.
- Transclusion: embed a whole page or a single block anywhere; edits show up
  everywhere. Synced blocks can be mirrored by copying a synced reference from
  the block menu and pasting it into another page. Circular embeds are detected
  and not rendered.
- Knowledge graph: hierarchy, references, tags and database relations; zoom,
  pan, drag, search, per-type filters, focus mode (1–3 steps) and a
  connection panel.

**Priority 3 — learning and productivity**
- Flashcards linked to your notes: write `Question :: Answer`,
  `Term ;; Definition` (two cards, both directions) or `{{cloze}}` gaps
  (`{{answer::hint}}`, `{{c1::…}}` groups) in any block. With nothing after
  `::`, the block's children are the answer. Cards update when the text
  changes and keep their history if the syntax is removed and restored.
- Cards can also be made from a block's menu ("Create flashcard…"), from
  selected text (toolbar `{}` button or `Ctrl/⌘ Shift C`) and in the card
  editor, including image occlusion (upload an image, drag boxes to hide).
- FSRS-5 scheduling with learning steps, sibling burying, configurable
  desired retention and daily new/review limits.
- Full-screen review: Space to reveal, `1`–`4` for Again/Hard/Good/Easy (with
  the next interval on each button), undo, edit, suspend, jump to source.
  Study everything, a deck, a page and its sub-pages, or pages with a tag.
- Dashboard: due today, new available, reviews and time today, 30-day
  recall, streak, 30-day forecast, 26-week activity, decks. Card browser
  with search, filters and bulk suspend/reset/move/delete.
- Tasks with description, priority, due and start dates, recurrence,
  project, page, tags. Views: Inbox, Today (with overdue), Upcoming,
  All open, Completed; search, filters and sorting. Quick add understands
  `tomorrow`, weekdays, `in 3 days`, `!1`–`!3`, `#tag`, `every week`.
- Checklist blocks become tasks (`Alt T` or block menu) and stay in sync both
  ways; completing a recurring task moves it to its next date. A task attached
  to a database entry marks the entry done (status or checkbox).
- Home shows today's tasks and cards; the sidebar shows badge counts; global
  search covers cards and tasks.

**Priority 4 — advanced functionality**
- File library (sidebar → Files): every upload with where it is used,
  previews (images, PDF, audio, video), rename, download, delete with a
  warning when still in use. Media blocks can reuse any uploaded file; PDF
  file blocks show an inline viewer.
- Built-in viewers in Files:
  - Audio/video player with seek bar (buffered range), volume, speed,
    keyboard shortcuts (Space/K, ←/→, J/L, ↑/↓, M, F, P, 0–9, `<` `>`),
    full screen and picture-in-picture for video, a waveform and cover view
    for audio. Esc or the minimise button keeps it playing in a corner dock
    while you browse other files and pages.
  - PDF viewer (pdf.js): thumbnails, zoom, page navigation, search, text
    selection, coloured highlights and notes. Annotations are stored in Kern,
    never in the file; "Save a copy" writes a new PDF with them burned in.
  - Text, Markdown and code files are editable in place (Markdown has a
    live preview). Each save keeps the previous content as a version
    (History, last 50), restorable at any time.
  - Word (.docx) documents are viewable, converted to HTML in the browser;
    they cannot be edited. Other office formats are download-only.
  - Media is streamed with HTTP range requests (Caddy in Docker, a
    range-aware fallback view in development), so big files seek instantly.
- Import: Markdown files or whole folders (front-matter tags, `[[wiki
  links]]` resolved by title, images brought along, Notion/Obsidian folder
  layout), HTML, OPML, CSV (becomes a database with inferred column types),
  Kern JSON, Anki `.apkg`, and `.zip` files of any of these.
- Export: a page (with or without sub-pages) as Markdown, HTML, PDF (print
  view), Kern JSON or OPML; databases as CSV or JSON; flashcards as CSV or
  Anki `.apkg`; the whole workspace as Markdown/HTML folders with attachments
  or as JSON.
- Version history: a snapshot is kept when you come back to a page after a
  pause, before restores, and on demand; older ones thin out to one per day
  and then per week. Browse, preview, compare with the current page
  (line diff) and restore.
- Offline: a service worker keeps the app and every page you have opened
  available offline. Edits made offline (or when the server is down) are
  stored on the device, survive reloads, and are saved when the connection
  returns. Every save carries the version it was based on; if the same blocks
  changed elsewhere, nothing is overwritten and you choose: keep both (your
  version becomes a separate page), use theirs, or use yours.
- Backups and restore (see above), storage overview.
- Saved searches: the search page (`/search`, or "All results" in the search
  palette) can save a query; saved searches appear in the sidebar as live
  views.
- Customization: theme, accent, font, text size, width, density, default
  block type, autosave speed, open-in-new-tab, sidebar sections, favorites,
  clear recent, configurable app shortcuts, flashcard limits and retention.
- API documentation at `/developer` (Settings → Data & backups links to it).

**Groups**

- A group is a dashboard for one subject, such as a class or a project
  (sidebar → Groups, or New page ▾ → Group; any page can be turned into one
  from its ⋯ menu). It shows its name large, buttons to create notes,
  calendars, boards and databases inside it, every database it holds working
  in place (calendars with month and week views), an Upcoming list of dated
  tasks and calendar entries from anywhere inside the group with quick task
  entry, the nested notes, and an overview page below.

**AI (optional)**

- Choose a provider in Settings → AI: Anthropic (Claude, through the official
  SDK), OpenAI, Gemini, OpenRouter, Ollama or any OpenAI-compatible server.
  The key stays on the server and is never sent back to the browser.
- Writing help in the editor (type `/` then a space), flashcards from a page
  (the ✦ next to New card), templates from a description (next to New
  template).
- Intelligence (sidebar) is a chat that can read and change the workspace:
  search, read and edit pages, create groups, add or move cards on boards and
  events on calendars, manage tasks and make flashcards. Each change is listed
  under its reply with a link. Pages it edits get a version-history snapshot
  first, and what it deletes goes to the trash. With non-Claude providers the
  model must support tool calling.
- Press Alt+I anywhere (also while typing; changeable in Settings →
  Shortcuts), or the ✦ in a page's top bar, to open Intelligence over the
  current page: ask about it, have it edit it, get quizzed on it (one question
  at a time, with a score and the missed questions offered as flashcards), or
  have it look things up. Each page keeps its own conversation, which also
  appears on the Intelligence page.
- With Claude it can search the web and read web pages, and lists the
  sources under its answer. Other providers have no web search; the popup
  says so.

## Development without Docker

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py kern_boot && .venv/bin/python manage.py runserver 127.0.0.1:8421
```

```bash
cd frontend && npm install && npm run dev
```

The Vite dev server proxies `/api`, `/media` and git traffic (`/git/<name>.git/…`) to
`127.0.0.1:8421`. Large pushes are sent chunked, which `runserver` cannot read; run the
backend with gunicorn (as in Docker) to test those.
Backend tests: `cd backend && .venv/bin/python manage.py test` (accounts, per-user isolation, and the notes app).
The setup code for a development server is printed by `kern_boot` (or set `KERN_SETUP_CODE`).
The service worker only runs in a production build: `npm run build && npm run preview`
(also proxies the API).
Frontend checks: `cd frontend && npm run check`.

## Layout

```
backend/   Django project (kern/) and app (notes/)
  notes/views.py      documents, blocks, links, tags, properties, search
  notes/views_db.py   databases, views, entries, templates, graph
  notes/views_learn.py flashcard and task endpoints
  notes/learning.py   card syntax, queues, statistics
  notes/fsrs.py       FSRS-5 scheduler
  notes/tasks.py      recurrence, task ⇄ block/entry sync
  notes/views_data.py files, versions, import/export, backups endpoints
  notes/gitrepo.py    git hosting: repo storage, safe git calls, tree/log/diff/stats
  notes/views_git.py  git API (/api/git) and smart-HTTP protocol (/git/<name>.git)
  notes/views_files.py in-place file edits with versions, PDF annotations, range-aware /media
  notes/porting.py    Markdown/HTML/OPML/CSV/JSON/Anki import and export
  notes/versions.py   version snapshots, pruning, restore
  notes/backup.py     backups, restore, automatic daily backup
  notes/dbcompute.py  rollups and formula evaluation per row
  notes/formula.py    formula parser/evaluator
  notes/search.py     SQLite FTS5 index
frontend/  SvelteKit single-page app, served by Caddy in production
  src/lib/editor/     block editor
  src/lib/db/         database views
  src/lib/learn/      flashcard editor and card rendering
  src/lib/tasks/      task list, detail panel, quick-add parser
  src/service-worker/ offline caching
docker-compose.yml
```
