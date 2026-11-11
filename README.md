# Kern

A self-hosted, single-user knowledge base: an outliner-style block editor with
linked pages, tags with properties, Notion-style relational databases, templates,
transclusion and a knowledge graph. Django + DRF + SQLite (FTS5) on the backend,
Svelte 5 / SvelteKit on the frontend, all in Docker.

## Run it

```bash
docker compose up -d --build
```

Then open <http://localhost:8420>.

- Data (the SQLite database and uploaded files) lives in the `kern_data` Docker
  volume and survives rebuilds, `docker compose down` and updates. Only
  `docker compose down -v` deletes it.
- Kern has no login. By default it only listens on `127.0.0.1`. Copy
  `.env.example` to `.env` to change the port, or to listen on your network
  (only do that on a network you trust).
- Update: `git pull && docker compose up -d --build`. Database migrations run
  automatically when the backend starts.

### Backups

Settings → Data & backups creates a backup (`.zip` with the database and all
uploaded files), restores one, and keeps an automatic daily backup (the last
7) inside the data volume. Restoring always saves a safety copy first. To copy
backups off the machine:

```bash
docker compose cp backend:/data/backups ./kern-backups
```

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

## Development without Docker

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py runserver 127.0.0.1:8421
```

```bash
cd frontend && npm install && npm run dev
```

The Vite dev server proxies `/api` and `/media` to `127.0.0.1:8421`.
Backend tests: `cd backend && .venv/bin/python manage.py test notes` (30 tests).
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
