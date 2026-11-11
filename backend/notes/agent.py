"""Intelligence: a chat assistant that can read and change the workspace through tools.

Every page it edits gets a version snapshot first (restorable from version history),
and deletions go to the trash, so nothing it does is permanent.
"""
import copy
import json
import uuid

from django.db import transaction
from kern import tenancy
from django.db.models import Max
from django.utils import timezone

from . import ai, learning, porting, search, tasks as tasks_mod, versions
from .models import Block, CardNote, Chat, Database, Document, PropertyDef, PropertyValue, Tag, Task
from .text import one_line, to_text

MAX_STEPS = 16

SYSTEM = """You are Intelligence, the assistant built into Kern, the user's personal notes app.
You can read and change their workspace with the tools: pages (nested notes), groups (dashboards
that gather the notes, databases and calendars for one subject, like a class), databases (tables,
kanban boards, calendars) and their entries, tasks, tags and flashcards.

How to work:
- Look things up before you change them: search or list, then read the page or database.
- Page content is Markdown: headings, "- " bullets (indent two spaces to nest), "1. " lists,
  "- [ ] " to-dos, > quotes, code fences, tables and [[Page title]] links. A line written as
  "Question :: Answer" becomes a flashcard.
- Kanban boards are databases: move a card by changing its Status property.
- Make the change the user asked for, then reply briefly with what you did. Mention page titles
  rather than ids.
- Before moving several pages to the trash or deleting a lot of content, ask the user to confirm,
  unless they clearly asked for exactly that.
- Edits are reversible: pages keep version history and deleted pages go to the trash.

Quizzing: when the user asks to be quizzed, read the relevant page first, then ask one question
at a time and wait for their answer. Mark each answer right or wrong in a sentence, add a short
explanation when they miss, then ask the next question. Mix recall, explanation and application
questions, and get harder as they do well. When they stop, or after about ten questions, give
the score and offer to save the questions they missed as flashcards on that page."""

WEB_ON = """

Web: you can search the web and read web pages. Use them when the user asks for more information,
for current facts, or for something their notes do not cover. Say briefly what you found and where,
and only put web material into their notes when they ask for that."""

WEB_OFF = """

Web: you cannot search the web with this provider (web search needs Claude). If the user asks for
something that needs it, say so plainly, then help from their notes and your own knowledge, and
say which is which."""

# Claude models with the current web tools (dynamic filtering); older Claude models get basic search.
WEB_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7",
              "claude-opus-4-6", "claude-sonnet-4-6")


def web_tools(cfg: dict) -> list[dict]:
    if cfg["provider"] != "anthropic":
        return []
    if cfg["model"].startswith(WEB_MODELS):
        return [{"type": "web_search_20260209", "name": "web_search"},
                {"type": "web_fetch_20260209", "name": "web_fetch"}]
    return [{"type": "web_search_20250305", "name": "web_search"}]


def tool(name, description, props, required=()):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props, "required": list(required),
                             "additionalProperties": False}}


S = {"type": "string"}
TOOLS = [
    tool("search", "Full-text search across pages, blocks, tags, flashcards and tasks.",
         {"query": S, "kind": {"type": "string", "enum": ["doc", "block", "tag", "card", "task"]}}, ["query"]),
    tool("list_pages", "List the pages, groups and databases directly inside a parent (or at the top level).",
         {"parent_id": {"type": "string", "description": "Omit for the top level."}}),
    tool("read_page", "Read a page: its title, tags, properties, sub-pages and content. Each content line starts with [id] for its block.",
         {"page_id": S}, ["page_id"]),
    tool("create_page", "Create a page (or a group dashboard) with optional Markdown content.",
         {"title": S, "parent_id": S, "markdown": S, "icon": {"type": "string", "description": "One emoji."},
          "kind": {"type": "string", "enum": ["page", "group"]}}, ["title"]),
    tool("add_to_page", "Add Markdown content to a page, at the end or right after a given block.",
         {"page_id": S, "markdown": S, "after_block_id": S}, ["page_id", "markdown"]),
    tool("replace_block", "Replace one block (and its nested blocks) with new Markdown content.",
         {"block_id": S, "markdown": S}, ["block_id", "markdown"]),
    tool("delete_blocks", "Delete blocks (with what is nested under them).",
         {"block_ids": {"type": "array", "items": S}}, ["block_ids"]),
    tool("update_page", "Rename, re-icon, move or tag a page.",
         {"page_id": S, "title": S, "icon": S, "parent_id": {"type": "string", "description": "New parent; \"root\" for the top level."},
          "add_tags": {"type": "array", "items": S}, "remove_tags": {"type": "array", "items": S}}, ["page_id"]),
    tool("trash_page", "Move a page and its sub-pages to the trash (they can be restored).", {"page_id": S}, ["page_id"]),
    tool("list_databases", "List databases (including kanban boards and calendars) with their properties and options.", {}),
    tool("query_database", "List the entries of a database with their property values.",
         {"database_id": S, "contains": {"type": "string", "description": "Only entries whose title or values contain this text."}}, ["database_id"]),
    tool("create_database", "Create a database: a table, a kanban board or a calendar.",
         {"title": S, "parent_id": S, "preset": {"type": "string", "enum": ["table", "kanban", "calendar"]}}, ["title"]),
    tool("add_entry", "Add an entry (row, card or event) to a database. values maps property names to values: text, number, true/false, ISO date, option name(s) for select/status/multi-select, page titles for relations.",
         {"database_id": S, "title": S, "values": {"type": "object"}, "markdown": S}, ["database_id", "title"]),
    tool("update_entry", "Change an entry's title or property values (e.g. move a kanban card by setting Status).",
         {"entry_id": S, "title": S, "values": {"type": "object"}}, ["entry_id"]),
    tool("list_tasks", "List tasks.", {"view": {"type": "string", "enum": ["today", "upcoming", "inbox", "open", "completed"]}}),
    tool("create_task", "Create a task.",
         {"title": S, "due": {"type": "string", "description": "YYYY-MM-DD"}, "priority": {"type": "integer", "minimum": 0, "maximum": 3},
          "project_id": {"type": "string", "description": "A page or group the task belongs to."},
          "recurrence": {"type": "string", "enum": ["day", "week", "month", "year"]}, "description": S}, ["title"]),
    tool("update_task", "Change or complete a task.",
         {"task_id": S, "title": S, "done": {"type": "boolean"}, "due": S, "priority": {"type": "integer"}}, ["task_id"]),
    tool("create_flashcards", "Create flashcards, optionally linked to a page.",
         {"cards": {"type": "array", "items": {"type": "object", "properties": {
             "kind": {"type": "string", "enum": ["basic", "cloze", "concept"]}, "front": S, "back": S},
             "required": ["front"], "additionalProperties": False}}, "page_id": S}, ["cards"]),
]


class ToolError(Exception):
    pass


# ------------------------------------------------------------------ helpers


def _uuid(v):
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        raise ToolError(f"“{v}” is not a valid id.")


def _doc(pid) -> Document:
    d = Document.objects.filter(id=_uuid(pid), trashed_at__isnull=True).first()
    if not d:
        raise ToolError("No page with that id (it may be in the trash).")
    return d


def _link(d: Document) -> dict:
    return {"id": str(d.id), "title": d.title or "Untitled", "icon": d.icon}


class Run:
    """One assistant turn: executes tools and records what changed."""

    def __init__(self):
        self.actions: list[dict] = []
        self.sources: list[dict] = []  # web pages the answer drew on
        self.snapshotted: set = set()

    def add_source(self, url, title=""):
        if url and url.startswith(("http://", "https://")) and all(x["url"] != url for x in self.sources):
            self.sources.append({"url": url, "title": (title or url)[:200]})

    def act(self, verb: str, d: Document | None = None, detail: str = ""):
        item = {"verb": verb, "detail": detail}
        if d is not None:
            item["page"] = _link(d)
        self.actions.append(item)

    def before_edit(self, d: Document):
        if d.id not in self.snapshotted:
            self.snapshotted.add(d.id)
            if d.blocks.exists():
                versions.snapshot(d, "ai")

    # -------------------------------------------------------------- tools

    def search(self, query, kind=None):
        rows, _ = search.search(query, kind, 15, 0)
        out = []
        for k, ref, doc_id, title, snippet in rows:
            out.append({"kind": k, "id": ref, "page_id": doc_id, "title": title.replace("\x01", "").replace("\x02", ""),
                        "snippet": snippet.replace("\x01", "").replace("\x02", "")})
        return out or "No matches."

    def list_pages(self, parent_id=None):
        parent = _doc(parent_id) if parent_id else None
        qs = Document.objects.filter(parent=parent, trashed_at__isnull=True, entry_of__isnull=True, is_template=False)
        out = []
        for d in qs.order_by("position"):
            db = Database.objects.filter(page=d).values_list("id", flat=True).first()
            out.append({"id": str(d.id), "title": d.title or "Untitled", "kind": "database" if db else d.kind,
                        "database_id": str(db) if db else None,
                        "children": Document.objects.filter(parent=d, trashed_at__isnull=True).count()})
        return out or "Nothing here."

    def read_page(self, page_id):
        from .views import doc_properties
        d = _doc(page_id)
        blocks = list(d.blocks.all())
        kids: dict = {}
        for b in blocks:
            kids.setdefault(b.parent_id, []).append(b)
        lines = []
        ex = porting.Exporter()

        def walk(parent, depth):
            for b in sorted(kids.get(parent, []), key=lambda x: x.position):
                solo = copy.copy(b)
                solo.parent_id = None
                text = "\n".join(ex.md_blocks([solo], 0)).strip() or f"({b.type})"
                if b.type == "database" and (b.props or {}).get("database"):
                    text = f"(database view, database_id {b.props['database']})"
                first, *rest = text.splitlines() or [""]
                pad = "  " * depth
                lines.append(f"{pad}[{b.id}] {first}")
                lines.extend(f"{pad}    {ln}" for ln in rest)
                walk(b.id, depth + 1)

        walk(None, 0)
        props = doc_properties(d, [str(t) for t in d.tags.values_list("id", flat=True)])
        values = {}
        for p in props["defs"]:
            v = ex.value_text(p, props["values"].get(p["id"]))
            if v:
                values[p["name"]] = v
        db = Database.objects.filter(page=d).first()
        return {
            "id": str(d.id), "title": d.title, "kind": d.kind, "icon": d.icon,
            "database_id": str(db.id) if db else None,
            "entry_of_database": str(d.entry_of_id) if d.entry_of_id else None,
            "tags": [t.name for t in d.tags.all()], "properties": values,
            "sub_pages": [_link(c) for c in d.children.filter(trashed_at__isnull=True).order_by("position")],
            "content": "\n".join(lines) or "(empty)",
        }

    def _insert(self, d: Document, markdown: str, parent_id=None, after: Block | None = None) -> int:
        from .views import apply_block_sync
        trees = porting.markdown_to_trees(markdown, porting.Ctx())
        if not trees:
            return 0
        siblings = list(Block.objects.filter(document=d, parent_id=parent_id).order_by("position"))
        if after is not None:
            i = next((n for n, b in enumerate(siblings) if b.id == after.id), len(siblings) - 1)
            lo = siblings[i].position
            hi = siblings[i + 1].position if i + 1 < len(siblings) else lo + len(trees) + 1
        else:
            lo = siblings[-1].position if siblings else 0
            hi = lo + len(trees) + 1
        step = (hi - lo) / (len(trees) + 1)
        upserts = []

        def add(t, parent, pos):
            bid = str(uuid.uuid4())
            upserts.append({"id": bid, "parent": parent, "position": pos, "type": t["type"], "html": t.get("html", ""),
                            "props": t.get("props") or {}, "collapsed": False})
            for j, c in enumerate(t.get("children") or []):
                add(c, bid, j + 1)

        for n, t in enumerate(trees):
            add(t, str(parent_id) if parent_id else None, lo + step * (n + 1))
        apply_block_sync(d, upserts, [])
        porting.resolve_wiki_links(_ctx_with(d))
        return len(trees)

    def create_page(self, title, parent_id=None, markdown="", icon="", kind="page"):
        parent = _doc(parent_id) if parent_id else None
        top = Document.objects.filter(parent=parent, trashed_at__isnull=True, entry_of__isnull=True).aggregate(m=Max("position"))["m"] or 0
        d = Document.objects.create(title=title[:500], parent=parent, icon=(icon or "")[:8], position=top + 1,
                                    kind="group" if kind == "group" else "page", last_opened_at=timezone.now())
        if markdown:
            self._insert(d, markdown)
        search.index_document(d)
        self.act("Created group" if d.kind == "group" else "Created page", d)
        return {"id": str(d.id)}

    def add_to_page(self, page_id, markdown, after_block_id=None):
        d = _doc(page_id)
        after = None
        if after_block_id:
            after = Block.objects.filter(id=_uuid(after_block_id), document=d).first()
            if not after:
                raise ToolError("That block is not on this page.")
        self.before_edit(d)
        n = self._insert(d, markdown, after.parent_id if after else None, after)
        self.act("Edited", d, f"added {n} block{'s' if n != 1 else ''}")
        return f"Added {n} blocks."

    def replace_block(self, block_id, markdown):
        from .views import apply_block_sync
        b = Block.objects.filter(id=_uuid(block_id), document__trashed_at__isnull=True).select_related("document").first()
        if not b:
            raise ToolError("No block with that id.")
        d = b.document
        self.before_edit(d)
        n = self._insert(d, markdown, b.parent_id, b)
        apply_block_sync(d, [], [str(b.id)])
        self.act("Edited", d, "rewrote a block")
        return f"Replaced with {n} blocks."

    def delete_blocks(self, block_ids):
        from .views import apply_block_sync
        blocks = list(Block.objects.filter(id__in=[_uuid(i) for i in block_ids]).select_related("document"))
        if not blocks:
            raise ToolError("None of those blocks exist.")
        by_doc: dict = {}
        for b in blocks:
            by_doc.setdefault(b.document, []).append(str(b.id))
        for d, ids in by_doc.items():
            self.before_edit(d)
            apply_block_sync(d, [], ids)
            self.act("Edited", d, f"removed {len(ids)} block{'s' if len(ids) != 1 else ''}")
        return f"Deleted {len(blocks)} blocks."

    def update_page(self, page_id, title=None, icon=None, parent_id=None, add_tags=None, remove_tags=None):
        d = _doc(page_id)
        changes = []
        if title is not None:
            d.title = title[:500]
            changes.append("renamed")
        if icon is not None:
            d.icon = icon[:8]
        if parent_id is not None:
            from .views import subtree_ids
            new_parent = None if parent_id == "root" else _doc(parent_id)
            if new_parent and new_parent.id in subtree_ids(d.id):
                raise ToolError("A page cannot be moved inside itself.")
            d.parent = new_parent
            changes.append("moved")
        d.updated_at = timezone.now()
        d.save()
        for name in add_tags or []:
            t = porting.Ctx().tag(str(name).lstrip("#"))
            d.tags.add(t)
            changes.append(f"tagged #{t.name}")
        for name in remove_tags or []:
            t = Tag.objects.filter(key=str(name).lstrip("#").lower()).first()
            if t:
                d.tags.remove(t)
                changes.append(f"untagged #{t.name}")
        search.index_document(d)
        self.act("Updated", d, ", ".join(changes))
        return "Done."

    def trash_page(self, page_id):
        from .views import subtree_ids
        d = _doc(page_id)
        Document.objects.filter(id__in=subtree_ids(d.id), trashed_at__isnull=True).update(trashed_at=timezone.now())
        self.act("Moved to trash", d)
        return "Moved to the trash."

    def list_databases(self):
        out = []
        for db in Database.objects.select_related("page").filter(page__trashed_at__isnull=True):
            out.append({
                "database_id": str(db.id), "title": db.page.title or "Untitled", "page_id": str(db.page_id),
                "views": [v.type for v in db.views.all()],
                "properties": [{"name": p.name, "type": p.type,
                                **({"options": [o["name"] for o in p.options]} if p.options else {})}
                               for p in db.properties.order_by("position")],
            })
        return out or "No databases yet."

    def query_database(self, database_id, contains=None):
        from . import dbcompute
        db = Database.objects.filter(id=_uuid(database_id)).first()
        if not db:
            raise ToolError("No database with that id.")
        defs = list(db.properties.order_by("position"))
        rows = list(db.entries.filter(trashed_at__isnull=True, is_template=False).order_by("position")[:500])
        vals = dbcompute.compute(rows, defs) if rows else {}
        ex = porting.Exporter()
        out = []
        for r in rows:
            v = {d.name: ex.value_text({"type": d.type, "options": d.options}, vals.get(r.id, {}).get(str(d.id))) for d in defs}
            v = {k: x for k, x in v.items() if x}
            item = {"entry_id": str(r.id), "title": r.title, "values": v}
            if contains and contains.lower() not in json.dumps(item, ensure_ascii=False).lower():
                continue
            out.append(item)
        return out or "No entries."

    def create_database(self, title, parent_id=None, preset="table"):
        from .views_db import apply_preset
        parent = _doc(parent_id) if parent_id else None
        top = Document.objects.filter(parent=parent, trashed_at__isnull=True, entry_of__isnull=True).aggregate(m=Max("position"))["m"] or 0
        page = Document.objects.create(parent=parent, title=title[:500], position=top + 1, last_opened_at=timezone.now())
        db = Database.objects.create(page=page)
        apply_preset(db, None if preset == "table" else preset)
        search.index_document(page)
        self.act({"kanban": "Created board", "calendar": "Created calendar"}.get(preset, "Created database"), page)
        return {"database_id": str(db.id), "page_id": str(page.id), "properties": self.list_databases_one(db)}

    def list_databases_one(self, db):
        return [{"name": p.name, "type": p.type, **({"options": [o["name"] for o in p.options]} if p.options else {})}
                for p in db.properties.order_by("position")]

    def _set_values(self, entry: Document, db: Database, values: dict):
        from .views import coerce_value
        from .views_db import sync_reverse
        from .util_colors import COLORS
        defs = {p.name.lower(): p for p in db.properties.all()}
        notes = []
        for name, raw in (values or {}).items():
            p = defs.get(str(name).lower())
            if not p:
                notes.append(f"no property “{name}”")
                continue
            if p.type in PropertyDef.COMPUTED:
                continue
            v = raw
            if p.type in ("select", "status", "multi_select"):
                names = raw if isinstance(raw, list) else [raw]
                ids = []
                for n in names:
                    if n in (None, ""):
                        continue
                    opt = next((o for o in p.options if o["name"].lower() == str(n).lower() or o["id"] == n), None)
                    if not opt:
                        if p.type == "status":
                            notes.append(f"“{n}” is not a {p.name} option ({', '.join(o['name'] for o in p.options)})")
                            continue
                        opt = {"id": str(uuid.uuid4()), "name": str(n)[:100], "color": COLORS[len(p.options) % len(COLORS)]}
                        p.options = [*p.options, opt]
                        p.save(update_fields=["options"])
                    ids.append(opt["id"])
                v = ids if p.type == "multi_select" else (ids[0] if ids else None)
            elif p.type == "relation":
                titles = raw if isinstance(raw, list) else [raw]
                target = (p.config or {}).get("target")
                pool = Document.objects.filter(trashed_at__isnull=True)
                if target:
                    pool = pool.filter(entry_of_id=target)
                ids = []
                for t in titles:
                    hit = pool.filter(title__iexact=str(t)).first() or (pool.filter(id=t).first() if _is_uuid(t) else None)
                    if hit:
                        ids.append(str(hit.id))
                    else:
                        notes.append(f"no page called “{t}” for {p.name}")
                v = ids
            try:
                v = coerce_value(p, v)
            except Exception:
                notes.append(f"bad value for {p.name}")
                continue
            old = PropertyValue.objects.filter(document=entry, definition=p).values_list("value", flat=True).first()
            PropertyValue.objects.update_or_create(document=entry, definition=p, defaults={"value": v})
            if p.type == "relation":
                sync_reverse(p, entry, set(old or []), set(v or []))
        search.index_document(entry)
        return notes

    def add_entry(self, database_id, title, values=None, markdown=""):
        db = Database.objects.filter(id=_uuid(database_id)).select_related("page").first()
        if not db:
            raise ToolError("No database with that id.")
        top = db.entries.aggregate(m=Max("position"))["m"] or 0
        e = Document.objects.create(entry_of=db, title=title[:500], position=top + 1)
        notes = self._set_values(e, db, values or {})
        if markdown:
            self._insert(e, markdown)
        self.act("Added", e, f"to {db.page.title or 'a database'}")
        return {"entry_id": str(e.id), **({"warnings": notes} if notes else {})}

    def update_entry(self, entry_id, title=None, values=None):
        e = _doc(entry_id)
        if not e.entry_of_id:
            raise ToolError("That page is not a database entry.")
        if title is not None:
            e.title = title[:500]
            e.save(update_fields=["title"])
        notes = self._set_values(e, e.entry_of, values or {})
        Document.objects.filter(id=e.id).update(updated_at=timezone.now())
        self.act("Updated", e, ", ".join(f"{k}: {v}" for k, v in (values or {}).items())[:120])
        return {"ok": True, **({"warnings": notes} if notes else {})}

    def list_tasks(self, view="open"):
        today = timezone.localdate()
        qs = Task.objects.exclude(document__trashed_at__isnull=False)
        qs = {"today": qs.filter(done=False, due__lte=today), "upcoming": qs.filter(done=False, due__gt=today),
              "inbox": qs.filter(done=False, due__isnull=True, project__isnull=True, document__isnull=True),
              "completed": qs.filter(done=True)}.get(view, qs.filter(done=False))
        return [{"task_id": str(t.id), "title": t.title, "due": t.due.isoformat() if t.due else None,
                 "priority": t.priority, "done": t.done} for t in qs.order_by("due")[:100]] or "No tasks."

    def create_task(self, title, due=None, priority=0, project_id=None, recurrence=None, description=""):
        import datetime as dt
        t = Task(title=title[:500], priority=max(0, min(3, int(priority or 0))), description=description or "")
        if due:
            t.due = dt.date.fromisoformat(due[:10])
        if project_id:
            t.project = _doc(project_id)
        if recurrence:
            t.recurrence = {"freq": recurrence, "interval": 1}
        t.position = (Task.objects.aggregate(m=Max("position"))["m"] or 0) + 1
        t.save()
        tasks_mod.index_task(t)
        self.act("Added task", None, title)
        return {"task_id": str(t.id)}

    def update_task(self, task_id, title=None, done=None, due=None, priority=None):
        import datetime as dt
        t = Task.objects.filter(id=_uuid(task_id)).first()
        if not t:
            raise ToolError("No task with that id.")
        if title is not None:
            t.title = title[:500]
        if due is not None:
            t.due = dt.date.fromisoformat(due[:10]) if due else None
        if priority is not None:
            t.priority = max(0, min(3, int(priority)))
        t.save()
        if done is not None:
            tasks_mod.set_done(t, bool(done))
        tasks_mod.index_task(t)
        self.act("Completed task" if done else "Updated task", None, t.title)
        return "Done."

    def create_flashcards(self, cards, page_id=None):
        doc = _doc(page_id) if page_id else None
        n = 0
        for c in cards:
            kind = c.get("kind") if c.get("kind") in ("basic", "cloze", "concept") else "basic"
            front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
            if not front or (kind != "cloze" and not back):
                continue
            note = CardNote.objects.create(kind=kind, front=porting.esc(front, quote=False), back=porting.esc(back, quote=False), document=doc)
            learning.ensure_cards(note)
            n += 1
        self.act("Created flashcards", doc, f"{n} cards")
        return f"Created {n} cards."


def _is_uuid(v):
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _ctx_with(d):
    ctx = porting.Ctx()
    ctx.docs = [d]
    return ctx


def execute(run: Run, name: str, args: dict) -> str:
    fn = getattr(run, name, None)
    if name not in {t["name"] for t in TOOLS} or fn is None:
        return json.dumps({"error": f"Unknown tool {name}."})
    try:
        with tenancy.atomic():
            result = fn(**(args or {}))
    except ToolError as e:
        return json.dumps({"error": str(e)})
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments: {e}"})
    except (ValueError, KeyError) as e:
        return json.dumps({"error": str(e)})
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)


# --------------------------------------------------------------------- loops


def context_note(page_id) -> str:
    today = timezone.localdate()
    note = f"Today is {today:%A %Y-%m-%d}."
    if page_id and _is_uuid(page_id):
        d = Document.objects.filter(id=page_id, trashed_at__isnull=True).first()
        if d:
            note += (f" The user is looking at the page “{d.title or 'Untitled'}” (id {d.id}); "
                     "“this page”, “this” and “here” mean it. Read it before answering about it.")
    return note


def chat_turn(chat: Chat, text: str, page_id=None) -> Chat:
    cfg = ai.config()
    if not ai.public_config()["configured"]:
        raise ai.AIError("The AI assistant is not set up yet. Choose a provider in Settings → AI.", 409)
    provider_family = "anthropic" if cfg["provider"] == "anthropic" else "openai"
    if chat.provider and chat.provider != provider_family:
        # The provider changed since this chat began: carry the conversation over as plain text.
        chat.history = [m for t in chat.transcript for m in
                        ([{"role": t["role"], "content": t["text"]}] if t.get("text") else [])]
    chat.provider = provider_family
    run = Run()
    user_msg = f"<context>{context_note(page_id)}</context>\n\n{text}"
    if provider_family == "anthropic":
        reply = _anthropic_loop(chat, cfg, user_msg, run)
    else:
        reply = _openai_loop(chat, cfg, user_msg, run)
    answer = {"role": "assistant", "text": reply, "actions": run.actions, "at": timezone.now().isoformat()}
    if run.sources:
        answer["sources"] = run.sources[:8]
    chat.transcript = [*chat.transcript, {"role": "user", "text": text, "at": timezone.now().isoformat()}, answer]
    if not chat.title:
        chat.title = one_line(text, 80)
    chat.save()
    return chat


def _anthropic_loop(chat: Chat, cfg: dict, user_msg: str, run: Run) -> str:
    import anthropic

    key = ai._get("ai_secret").get("api_key", "")
    client = anthropic.Anthropic(api_key=key, timeout=300.0, max_retries=2)
    messages = [*chat.history, {"role": "user", "content": user_msg}]
    use_fallbacks = cfg["model"] in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
    web = web_tools(cfg)
    system = SYSTEM + (WEB_ON if web else WEB_OFF)
    reply, container = "", None
    for _ in range(MAX_STEPS):
        kwargs = dict(model=cfg["model"], max_tokens=ai.MAX_TOKENS, system=system, tools=[*TOOLS, *web], messages=messages)
        if cfg["model"].startswith(ai.EFFORT_MODELS):
            kwargs["output_config"] = {"effort": "medium"}
        if container:
            kwargs["container"] = container  # web search filters results in a code container; keep using it
        try:
            if use_fallbacks:
                msg = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                msg = client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise ai.AIError("Anthropic rejected the API key. Check it in Settings → AI.", 401)
        except anthropic.NotFoundError:
            raise ai.AIError(f"Model “{cfg['model']}” was not found.", 404)
        except anthropic.RateLimitError:
            raise ai.AIError("Anthropic's rate limit was reached. Try again in a minute.", 429)
        except anthropic.BadRequestError as e:
            raise ai.AIError(f"Anthropic refused the request: {e.message}", 400)
        except anthropic.APIStatusError as e:
            raise ai.AIError(f"Anthropic returned an error ({e.status_code}). Try again shortly.", 502)
        except anthropic.APIConnectionError:
            raise ai.AIError("Could not reach Anthropic.", 502)
        # Keep the assistant turn exactly as returned (thinking and tool-use blocks included).
        content = [b.model_dump(mode="json", exclude_none=True) for b in msg.content]
        messages.append({"role": "assistant", "content": content})
        if getattr(msg, "container", None):
            container = msg.container.id
        collect_sources(run, content)
        # Web answers arrive as several text blocks (split at citations): join this turn's text.
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if text:
            reply = text
        if msg.stop_reason == "refusal":
            reply = "I can't help with that request."
            break
        if msg.stop_reason == "pause_turn":
            continue
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            break
        results = [{"type": "tool_result", "tool_use_id": c.id, "content": execute(run, c.name, c.input)} for c in calls]
        messages.append({"role": "user", "content": results})
    else:
        reply += "\n\n(I stopped after many steps. Ask me to continue if there is more to do.)"
    chat.history = messages
    return reply or "Done."


def collect_sources(run: Run, content: list[dict]) -> None:
    """Pages the answer cites first, then (if it cites none) the pages its searches found."""
    found = []
    for b in content:
        if b.get("type") == "text":
            for c in b.get("citations") or []:
                run.add_source(c.get("url"), c.get("title"))
        elif b.get("type") == "web_search_tool_result":
            results = b.get("content")
            if isinstance(results, list):  # an error comes back as an object instead
                found += [(r.get("url"), r.get("title")) for r in results if isinstance(r, dict)]
        elif b.get("type") == "web_fetch_tool_result":
            c = b.get("content")
            if isinstance(c, dict) and c.get("url"):
                found.append((c.get("url"), (c.get("content") or {}).get("title") if isinstance(c.get("content"), dict) else ""))
    if not run.sources:
        for url, title in found[:5]:
            run.add_source(url, title)


def _openai_loop(chat: Chat, cfg: dict, user_msg: str, run: Run) -> str:
    import urllib.request
    import urllib.error

    key = ai._get("ai_secret").get("api_key", "")
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]
    messages = [*chat.history, {"role": "user", "content": user_msg}]
    reply = ""
    for _ in range(MAX_STEPS):
        body = json.dumps({"model": cfg["model"], "messages": [{"role": "system", "content": SYSTEM + WEB_OFF}, *messages],
                           "tools": tools, "max_tokens": ai.MAX_TOKENS}).encode()
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
        req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as res:
                data = json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            raise ai.AIError(f"The provider returned an error ({e.code}). Does this model support tools?", 502)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ai.AIError(f"Could not reach {cfg['base_url']} ({getattr(e, 'reason', e)}).", 502)
        try:
            m = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ai.AIError("The provider sent an answer Kern could not read.", 502)
        entry = {"role": "assistant", "content": m.get("content") or ""}
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        messages.append(entry)
        if m.get("content"):
            reply = m["content"]
        if not m.get("tool_calls"):
            break
        for call in m["tool_calls"]:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": execute(run, call["function"]["name"], args)})
    else:
        reply += "\n\n(I stopped after many steps. Ask me to continue if there is more to do.)"
    chat.history = messages
    return reply or "Done."
