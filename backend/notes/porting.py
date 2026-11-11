"""Import and export: Markdown, HTML, OPML, CSV, JSON and Anki packages."""
import csv
import hashlib
import html as html_lib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree

from django.core.files.base import ContentFile
from django.db.models import Max
from django.utils import timezone

from . import learning, search
from .models import (
    Attachment, Block, Card, CardNote, Database, DbView, Deck, Document, PropertyDef, PropertyValue, Tag,
)
from .text import one_line, sanitize, to_text

esc = html_lib.escape


def uid() -> str:
    return str(uuid.uuid4())


def tree(btype, html="", props=None, children=None) -> dict:
    props = dict(props or {})
    if btype == "todo":
        props.setdefault("checked", False)
    if btype == "callout":
        props.setdefault("icon", "💡")
    return {"type": btype, "html": html, "props": props, "children": children or []}


# ================================================================== Markdown in

CODE_SPAN = re.compile(r"`([^`]+)`")


class Ctx:
    """State shared across one import: tags, wiki links to resolve, attachments."""

    def __init__(self):
        self.tags: dict[str, Tag] = {}
        self.files: dict[str, str] = {}  # path inside the import -> media url
        self.docs: list[Document] = []

    def tag(self, name: str) -> Tag:
        key = name.lower()
        if key not in self.tags:
            t = Tag.objects.filter(key=key).first()
            if not t:
                t = Tag.objects.create(name=name)
                search.index_tag(t)
            self.tags[key] = t
        return self.tags[key]


def inline_md(text: str, ctx: Ctx | None, base_dir: str = "") -> str:
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{esc(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = CODE_SPAN.sub(keep, text)
    out = esc(text, quote=False)
    out = re.sub(r"\$([^$\s][^$]*?)\$", lambda m: f'<span class="math" data-math="{esc(m.group(1))}" contenteditable="false">{esc(m.group(1))}</span>', out)
    out = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", lambda m: esc(m.group(1)), out)  # inline images: alt text
    out = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", lambda m: f"<i>{m.group(1) or m.group(2)}</i>", out)
    out = re.sub(r"~~(.+?)~~", r"<s>\1</s>", out)
    out = re.sub(r"==(.+?)==", r"<mark>\1</mark>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    # [[Page]] and [[Page|alias]] become links once every page exists.
    out = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: f"\x01{m.group(1).strip()}\x02{(m.group(2) or m.group(1)).strip()}\x03", out)
    if ctx is not None:
        def tagify(m):
            t = ctx.tag(m.group(2))
            return f'{m.group(1)}<a class="ref tag" data-ref="tag:{t.id}" href="/tag/{t.id}" contenteditable="false">#{esc(t.name)}</a>'
        out = re.sub(r"(^|\s)#([\w][\w/-]*)", tagify, out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)
    return out


LIST_RE = re.compile(r"^([-*+•]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$")


def parse_front_matter(text: str):
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                m = re.match(r"^(\w[\w -]*):\s*(.*)$", line)
                if m:
                    key, val = m.group(1).strip().lower(), m.group(2).strip()
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                    meta[key] = val
                elif line.strip().startswith("- ") and meta:
                    last = list(meta)[-1]
                    if not isinstance(meta[last], list):
                        meta[last] = [] if meta[last] == "" else [meta[last]]
                    meta[last].append(line.strip()[2:].strip().strip("'\""))
            text = text[end + 4:].lstrip("\n")
    return meta, text


def markdown_to_trees(text: str, ctx: Ctx | None = None, base_dir: str = "") -> list[dict]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    root: list[dict] = []
    stack: list[tuple[int, dict]] = []
    para: list[str] = []
    i = 0

    def flush_para():
        if para:
            root_or_parent(0).append(tree("paragraph", "<br>".join(inline_md(p, ctx, base_dir) for p in para)))
            para.clear()

    def root_or_parent(indent):
        while stack and stack[-1][0] >= indent:
            stack.pop()
        return stack[-1][1]["children"] if stack and indent > 0 else root

    def image(src, alt):
        url = src
        if not re.match(r"^[a-z]+:", src) and ctx is not None:
            key = os.path.normpath(os.path.join(base_dir, src.split("#")[0].split("?")[0])).replace("\\", "/")
            url = ctx.files.get(key) or ctx.files.get(os.path.basename(key)) or src
        btype = "image"
        lower = url.lower().split("?")[0]
        if lower.endswith((".mp4", ".webm", ".mov")):
            btype = "video"
        elif lower.endswith((".mp3", ".wav", ".ogg", ".m4a")):
            btype = "audio"
        elif lower.endswith(".pdf"):
            btype = "file"
        return tree(btype, "", {"url": url, "name": alt or os.path.basename(url), "caption": alt})

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        indent = len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip(" "))
        if not stripped:
            flush_para()
            stack.clear()
            i += 1
            continue
        fence = re.match(r"^(```|~~~)\s*(\S*)", stripped)
        if fence:
            flush_para()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                body.append(lines[i])
                i += 1
            root_or_parent(indent).append(tree("code", esc("\n".join(body), quote=False), {"language": fence.group(2)}))
            i += 1
            continue
        if stripped.startswith("$$"):
            flush_para()
            body = [stripped[2:]]
            if not (stripped.endswith("$$") and len(stripped) > 3):
                i += 1
                while i < len(lines) and "$$" not in lines[i]:
                    body.append(lines[i])
                    i += 1
                if i < len(lines):
                    body.append(lines[i].split("$$")[0])
            tex = "\n".join(body).replace("$$", "").strip()
            root.append(tree("equation", "", {"tex": tex}))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            root.append(tree("divider"))
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|?\s*:?-{2,}", lines[i].strip()):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    rows.append([inline_md(c, ctx, base_dir) for c in cells])
                i += 1
            width = max(len(r) for r in rows)
            root.append(tree("table", "", {"rows": [r + [""] * (width - len(r)) for r in rows], "header": True}))
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h and indent == 0:
            flush_para()
            stack.clear()
            level = min(3, len(h.group(1)))
            root.append(tree(f"h{level}", inline_md(h.group(2).rstrip("#").strip(), ctx, base_dir)))
            i += 1
            continue
        img = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)$", stripped)
        if img:
            flush_para()
            root_or_parent(indent).append(image(img.group(2), img.group(1)))
            i += 1
            continue
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            callout = re.match(r"^\[!(\w+)\]\s*(.*)$", quote[0]) if quote else None
            if callout:
                icons = {"note": "📝", "tip": "💡", "warning": "⚠️", "important": "❗", "caution": "⚠️", "info": "ℹ️"}
                body = [callout.group(2)] + quote[1:] if callout.group(2) else quote[1:]
                root.append(tree("callout", "<br>".join(inline_md(q, ctx, base_dir) for q in body if q),
                                 {"icon": icons.get(callout.group(1).lower(), "💡")}))
            else:
                root.append(tree("quote", "<br>".join(inline_md(q, ctx, base_dir) for q in quote if q)))
            continue
        lm = LIST_RE.match(stripped)
        if lm:
            flush_para()
            marker, box, body = lm.groups()
            if box:
                node = tree("todo", inline_md(body, ctx, base_dir), {"checked": "x" in box.lower()})
            elif marker[0].isdigit():
                node = tree("numbered", inline_md(body, ctx, base_dir))
            else:
                node = tree("bullet", inline_md(body, ctx, base_dir))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            (stack[-1][1]["children"] if stack else root).append(node)
            stack.append((indent, node))
            i += 1
            continue
        if stack and indent > stack[-1][0]:
            # Continuation text inside a list item becomes a child paragraph.
            stack[-1][1]["children"].append(tree("paragraph", inline_md(stripped, ctx, base_dir)))
            i += 1
            continue
        stack.clear()
        para.append(stripped)
        i += 1
    flush_para()
    return root


# ====================================================================== HTML in


class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


VOID = {"br", "img", "hr", "input", "meta", "link", "source", "col", "area", "base", "wbr"}


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.cur = self.root
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag == "title":
            self._in_title = True
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.cur.tag not in ("script", "style", "title", "head"):
            self.cur.children.append(data)


INLINE_MAP = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u", "s": "s", "strike": "s", "del": "s",
              "code": "code", "mark": "mark", "sub": "sub", "sup": "sup"}
BLOCKISH = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "hr", "table",
            "section", "article", "header", "footer", "main", "aside", "figure", "img", "details", "dl", "nav", "body", "html"}


def inline_html(node: Node) -> str:
    out = ""
    for c in node.children:
        if isinstance(c, str):
            out += esc(re.sub(r"\s+", " ", c), quote=False)
        elif c.tag == "br":
            out += "<br>"
        elif c.tag == "a" and re.match(r"^(https?:|mailto:)", c.attrs.get("href") or ""):
            out += f'<a href="{esc(c.attrs["href"])}">{inline_html(c)}</a>'
        elif c.tag in INLINE_MAP:
            inner = inline_html(c)
            if inner.strip():
                out += f"<{INLINE_MAP[c.tag]}>{inner}</{INLINE_MAP[c.tag]}>"
        elif c.tag in ("script", "style", "ul", "ol", "input"):
            continue
        else:
            out += inline_html(c)
    return out


def _trim(h: str) -> str:
    return re.sub(r"^(\s|&nbsp;|<br>)+|(\s|&nbsp;|<br>)+$", "", h)


def html_list(node: Node) -> list[dict]:
    out = []
    for li in node.children:
        if isinstance(li, str) or li.tag != "li":
            if not isinstance(li, str) and li.tag in ("ul", "ol") and out:
                out[-1]["children"] += html_list(li)
            continue
        box = next((c for c in li.children if not isinstance(c, str) and c.tag == "input" and c.attrs.get("type") == "checkbox"), None)
        kids = []
        for c in li.children:
            if not isinstance(c, str) and c.tag in ("ul", "ol"):
                kids += html_list(c)
        body = _trim(inline_html(li))
        if box is not None:
            out.append(tree("todo", body, {"checked": "checked" in box.attrs}, kids))
        else:
            out.append(tree("numbered" if node.tag == "ol" else "bullet", body, None, kids))
    return out


def html_walk(node: Node, out: list[dict]):
    run = Node("span")

    def flush():
        h = _trim(inline_html(run))
        if h:
            out.append(tree("paragraph", h))
        run.children = []

    for c in node.children:
        if isinstance(c, str) or c.tag not in BLOCKISH:
            if not isinstance(c, str) and c.tag == "br":
                flush()
            else:
                run.children.append(c)
            continue
        flush()
        t = c.tag
        if re.match(r"^h[1-6]$", t):
            h = _trim(inline_html(c))
            if h:
                out.append(tree(f"h{min(3, int(t[1]))}", h))
        elif t in ("ul", "ol"):
            out += html_list(c)
        elif t == "blockquote":
            h = _trim(inline_html(c))
            if h:
                out.append(tree("quote", h))
        elif t == "pre":
            out.append(tree("code", esc(c.text(), quote=False)))
        elif t == "hr":
            out.append(tree("divider"))
        elif t == "img":
            src = c.attrs.get("src", "")
            if re.match(r"^(https?:|/media/)", src):
                out.append(tree("image", "", {"url": src, "name": c.attrs.get("alt", ""), "caption": c.attrs.get("alt", "")}))
        elif t == "table":
            rows = []
            stack = [c]
            while stack:
                n = stack.pop(0)
                for k in n.children:
                    if isinstance(k, str):
                        continue
                    if k.tag == "tr":
                        rows.append([_trim(inline_html(td)) for td in k.children if not isinstance(td, str) and td.tag in ("td", "th")])
                    else:
                        stack.append(k)
            width = max((len(r) for r in rows), default=0)
            if width:
                out.append(tree("table", "", {"rows": [r + [""] * (width - len(r)) for r in rows], "header": True}))
        else:
            html_walk(c, out)
    flush()


def html_to_trees(text: str) -> tuple[str, list[dict]]:
    b = TreeBuilder()
    b.feed(text)
    out: list[dict] = []
    html_walk(b.root, out)
    title = b.title.strip()
    if out and out[0]["type"] == "h1" and (not title or to_text(out[0]["html"]).strip() == title):
        title = to_text(out.pop(0)["html"]).strip()
    return title, out


# ====================================================================== OPML in


def opml_to_trees(text: str) -> tuple[str, list[dict]]:
    root = ElementTree.fromstring(text.encode() if isinstance(text, str) else text)
    title = (root.findtext("head/title") or "").strip()

    def walk(el) -> list[dict]:
        out = []
        for o in el.findall("outline"):
            node = tree("bullet", esc(o.get("text") or o.get("title") or "", quote=False), None, walk(o))
            note = o.get("_note")
            if note:
                node["children"].insert(0, tree("paragraph", esc(note, quote=False).replace("\n", "<br>")))
            out.append(node)
        return out

    body = root.find("body")
    return title, walk(body) if body is not None else []


# =============================================================== creating docs


def insert_trees(doc: Document, trees: list[dict], parent_id=None, start: float = 1) -> list[Block]:
    created: list[Block] = []

    def add(t, parent, pos):
        btype = t["type"]
        html = sanitize(t.get("html", "")) if btype != "code" else t.get("html", "")
        props = t.get("props") or {}
        if btype == "table":
            props["rows"] = [[sanitize(c) for c in r] for r in props.get("rows", [])]
        b = Block(id=uuid.uuid4(), document=doc, parent_id=parent, position=pos, type=btype, html=html, props=props,
                  collapsed=bool(t.get("collapsed")))
        created.append(b)
        for j, k in enumerate(t.get("children") or []):
            add(k, b.id, j + 1)

    for j, t in enumerate(trees):
        add(t, parent_id, start + j)
    Block.objects.bulk_create(created)
    return created


def finish_doc(doc: Document, blocks: list[Block]) -> None:
    from .views import reindex_blocks
    reindex_blocks(doc, blocks)
    learning.sync_blocks(doc, [b.id for b in blocks])
    search.index_document(doc)


def resolve_wiki_links(ctx: Ctx) -> None:
    """Turn [[Title]] markers into links to imported or existing pages."""
    titles = {}
    for d in Document.objects.filter(trashed_at__isnull=True, is_template=False).only("id", "title"):
        titles.setdefault(d.title.strip().lower(), d)
    for d in ctx.docs:
        titles[d.title.strip().lower()] = d
    marker = re.compile(r"\x01(.*?)\x02(.*?)\x03")

    def fix(text):
        def repl(m):
            name, label = html_lib.unescape(m.group(1)), m.group(2)
            target = titles.get(name.split("#")[0].strip().lower())
            if not target:
                return f"[[{label}]]"
            return f'<a class="ref" data-ref="doc:{target.id}" href="/doc/{target.id}" contenteditable="false">{label}</a>'
        return marker.sub(repl, text)

    from .views import reindex_blocks
    for d in ctx.docs:
        changed = []
        for b in d.blocks.all():
            new = fix(b.html)
            if b.type == "table":
                rows = [[fix(c) for c in r] for r in (b.props or {}).get("rows", [])]
                if rows != (b.props or {}).get("rows"):
                    b.props = {**b.props, "rows": rows}
                    changed.append(b)
                    continue
            if new != b.html:
                b.html = new
                changed.append(b)
        if changed:
            Block.objects.bulk_update(changed, ["html", "props"])
            reindex_blocks(d, changed)


def new_doc(title: str, parent: Document | None, icon: str = "") -> Document:
    top = Document.objects.filter(parent=parent, trashed_at__isnull=True, entry_of__isnull=True).aggregate(
        m=Max("position"))["m"] or 0
    return Document.objects.create(parent=parent, title=title[:500], icon=icon[:64], position=top + 1,
                                   last_opened_at=timezone.now())


def save_file(name: str, data: bytes, mime: str = "") -> str:
    import mimetypes
    mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    a = Attachment(name=os.path.basename(name)[:255], mime=mime[:127], size=len(data))
    ext = "".join(ch for ch in (name.rsplit(".", 1)[-1] if "." in name else "") if ch.isalnum())[:10]
    a.file.save(f"{a.id}.{ext.lower()}" if ext else str(a.id), ContentFile(data), save=True)
    return a.file.url


MEDIA_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif", "mp4", "webm", "mov", "mp3", "wav", "ogg",
             "m4a", "pdf"}


def import_files(entries: list[tuple[str, bytes]], parent: Document | None) -> dict:
    """Import a set of files (from a folder, a zip, or a multi-select).

    entries: (relative path, bytes). Folders become nested pages.
    """
    ctx = Ctx()
    expanded: list[tuple[str, bytes]] = []
    for path, data in entries:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if not info.is_dir() and not info.filename.startswith("__MACOSX"):
                        expanded.append((info.filename, z.read(info)))
        else:
            expanded.append((path, data))
    entries = [(p.replace("\\", "/").lstrip("/"), d) for p, d in expanded]
    summary = {"pages": 0, "databases": 0, "cards": 0, "files": 0, "skipped": []}

    # Media first, so documents can point at uploaded copies.
    for path, data in entries:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in MEDIA_EXT:
            url = save_file(path, data)
            ctx.files[os.path.normpath(path)] = url
            ctx.files.setdefault(os.path.basename(path), url)
            summary["files"] += 1

    folders: dict[str, Document] = {}

    def folder_doc(folder: str) -> Document | None:
        if not folder or folder == ".":
            return parent
        if folder in folders:
            return folders[folder]
        up = folder_doc(os.path.dirname(folder))
        name = os.path.basename(folder)
        # A page "Name.md" next to folder "Name/" is that folder's page (Notion/Obsidian layout).
        d = new_doc(name, up)
        ctx.docs.append(d)
        folders[folder] = d
        summary["pages"] += 1
        return d

    text_entries = sorted(
        [(p, d) for p, d in entries if p.rsplit(".", 1)[-1].lower() in ("md", "markdown", "txt", "html", "htm", "opml", "csv", "json", "apkg", "colpkg")],
        key=lambda e: (e[0].count("/"), e[0]),
    )
    for path, data in text_entries:
        ext = path.rsplit(".", 1)[-1].lower()
        folder = os.path.dirname(path)
        stem = re.sub(r"\s+[0-9a-f]{32}$", "", os.path.basename(path).rsplit(".", 1)[0])  # Notion ids
        try:
            if ext == "apkg" or ext == "colpkg":
                r = import_anki(data)
                summary["cards"] += r["cards"]
                continue
            if ext == "json":
                r = import_kern_json(json.loads(data.decode("utf-8-sig")), folder_doc(folder))
                summary["pages"] += r["pages"]
                summary["databases"] += r["databases"]
                continue
            if ext == "csv":
                import_csv(data.decode("utf-8-sig"), stem, folder_doc(folder))
                summary["databases"] += 1
                continue
            text = data.decode("utf-8-sig", errors="replace")
            if ext in ("html", "htm"):
                title, trees = html_to_trees(text)
                title = title or stem
                meta = {}
            elif ext == "opml":
                title, trees = opml_to_trees(text)
                title = title or stem
                meta = {}
            else:
                meta, body = parse_front_matter(text)
                trees = markdown_to_trees(body, ctx, folder)
                title = str(meta.get("title") or stem)
                if trees and trees[0]["type"] == "h1" and to_text(trees[0]["html"]).strip() == title:
                    trees.pop(0)
            sibling_folder = os.path.join(folder, stem) if folder else stem
            if sibling_folder in folders:
                doc = folders[sibling_folder]
                doc.title = title[:500]
                doc.save(update_fields=["title"])
            else:
                doc = new_doc(title, folder_doc(folder))
                ctx.docs.append(doc)
                summary["pages"] += 1
                folders[sibling_folder] = doc
            blocks = insert_trees(doc, trees)
            tags = meta.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in re.split(r"[,\s]+", tags) if t.strip()]
            if tags:
                doc.tags.add(*[ctx.tag(str(t).lstrip("#")) for t in tags])
            finish_doc(doc, blocks)
        except Exception as e:  # keep importing the rest
            summary["skipped"].append(f"{path}: {e}")
    resolve_wiki_links(ctx)
    for d in ctx.docs:
        search.index_document(d)
    return summary


# ======================================================================= CSV in


def import_csv(text: str, title: str, parent: Document | None) -> Database:
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The CSV file is empty.")
    header, body = rows[0], rows[1:]
    page = new_doc(title, parent)
    db = Database.objects.create(page=page)
    DbView.objects.create(database=db, name="Table", type="table", position=1)

    def kind(values):
        vals = [v.strip() for v in values if v.strip()]
        if not vals:
            return "text"
        if all(re.fullmatch(r"-?\d+(?:[.,]\d+)?", v) for v in vals):
            return "number"
        if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", v) for v in vals):
            return "date"
        if all(v.lower() in ("true", "false", "yes", "no", "x", "", "✓", "checked", "unchecked") for v in vals):
            return "boolean"
        if all(re.fullmatch(r"https?://\S+", v) for v in vals):
            return "url"
        if all(re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v) for v in vals):
            return "email"
        distinct = {v for v in vals}
        if len(vals) >= 4 and len(distinct) <= max(3, len(vals) // 3) and len(distinct) <= 20:
            return "select"
        return "text"

    defs = []
    for col, name in enumerate(header[1:], start=1):
        values = [r[col] if col < len(r) else "" for r in body]
        t = kind(values)
        options = []
        if t == "select":
            from .util_colors import COLORS
            options = [{"id": uid(), "name": v, "color": COLORS[i % len(COLORS)]}
                       for i, v in enumerate(sorted({v.strip() for v in values if v.strip()}))]
        defs.append(PropertyDef.objects.create(database=db, name=(name.strip() or f"Column {col}")[:120], type=t,
                                               options=options, position=col))
    for pos, r in enumerate(body, start=1):
        entry = Document.objects.create(entry_of=db, title=(r[0] if r else "")[:500], position=pos)
        vals = []
        for col, d in enumerate(defs, start=1):
            raw = (r[col] if col < len(r) else "").strip()
            if not raw:
                continue
            v = raw
            if d.type == "number":
                v = float(raw.replace(",", "."))
            elif d.type == "date":
                v = raw[:10]
            elif d.type == "boolean":
                v = raw.lower() in ("true", "yes", "x", "✓", "checked")
            elif d.type == "select":
                v = next((o["id"] for o in d.options if o["name"] == raw), None)
            vals.append(PropertyValue(document=entry, definition=d, value=v))
        PropertyValue.objects.bulk_create(vals)
        search.index_document(entry)
    search.index_document(page)
    return db


# ======================================================================= JSON


def export_kern_json(root_ids: list) -> dict:
    """Pages (with sub-pages), their blocks, tags, properties and databases."""
    from .views import subtree_ids
    ids = []
    for r in root_ids:
        ids += [i for i in subtree_ids(r) if i not in ids]
    docs = list(Document.objects.filter(id__in=ids, is_template=False).prefetch_related("tags"))
    dbs = list(Database.objects.filter(page_id__in=ids))
    defs = list(PropertyDef.objects.filter(database__in=dbs))
    values: dict = {}
    tag_defs = {}
    for pv in PropertyValue.objects.filter(document_id__in=ids).select_related("definition"):
        values.setdefault(str(pv.document_id), {})[str(pv.definition_id)] = pv.value
        d = pv.definition
        if not d.database_id:
            tag_defs[str(d.id)] = {"id": str(d.id), "name": d.name, "type": d.type, "options": d.options,
                                   "tag": d.tag.name if d.tag_id else None}
    return {
        "format": "kern", "version": 1, "exported_at": timezone.now().isoformat(),
        "documents": [
            {
                "id": str(d.id), "parent": str(d.parent_id) if d.parent_id else None,
                "entry_of": str(d.entry_of_id) if d.entry_of_id else None,
                "title": d.title, "icon": d.icon, "cover": d.cover, "position": d.position,
                "is_favorite": d.is_favorite, "is_archived": d.is_archived,
                "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat(),
                "tags": [t.name for t in d.tags.all()],
                "values": values.get(str(d.id), {}),
                "blocks": [
                    {"id": str(b.id), "parent": str(b.parent_id) if b.parent_id else None, "position": b.position,
                     "type": b.type, "html": b.html, "props": b.props, "collapsed": b.collapsed}
                    for b in d.blocks.order_by("position")
                ],
            }
            for d in docs
        ],
        "databases": [
            {"id": str(db.id), "page": str(db.page_id),
             "properties": [{"id": str(p.id), "name": p.name, "type": p.type, "options": p.options,
                             "config": p.config, "position": p.position} for p in defs if p.database_id == db.id],
             "views": [{"name": v.name, "type": v.type, "config": v.config, "position": v.position}
                       for v in db.views.all()]}
            for db in dbs
        ],
        "tag_properties": list(tag_defs.values()),
    }


def import_kern_json(data: dict, parent: Document | None) -> dict:
    if data.get("format") != "kern":
        raise ValueError("Not a Kern export (expected \"format\": \"kern\").")
    idmap: dict[str, str] = {}
    for d in data.get("documents", []):
        idmap[d["id"]] = uid()
        for b in d.get("blocks", []):
            idmap[b["id"]] = uid()
    for db in data.get("databases", []):
        idmap[db["id"]] = uid()
        for p in db.get("properties", []):
            idmap[p["id"]] = uid()
    for p in data.get("tag_properties", []):
        idmap[p["id"]] = uid()

    def remap(value):
        text = json.dumps(value)
        text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                      lambda m: idmap.get(m.group(0), m.group(0)), text)
        return json.loads(text)

    ctx = Ctx()
    doc_rows = data.get("documents", [])
    present = {d["id"] for d in doc_rows}
    created: dict[str, Document] = {}
    # Parents before children.
    pending = list(doc_rows)
    guard = 0
    while pending and guard < 10000:
        guard += 1
        d = pending.pop(0)
        p = d.get("parent")
        if p in present and idmap[p] not in created:
            pending.append(d)
            continue
        doc = Document(
            id=idmap[d["id"]], title=d.get("title", "")[:500], icon=d.get("icon", "")[:64], cover=d.get("cover", ""),
            position=d.get("position", 0), is_favorite=d.get("is_favorite", False),
            is_archived=d.get("is_archived", False), last_opened_at=timezone.now(),
            parent=created.get(idmap.get(p)) if p in present else (parent if not d.get("entry_of") else None),
        )
        doc.save()
        created[str(doc.id)] = doc
        ctx.docs.append(doc)
    for db in data.get("databases", []):
        page = created.get(idmap.get(db["page"]))
        if not page:
            continue
        new_db = Database.objects.create(id=idmap[db["id"]], page=page)
        for p in db.get("properties", []):
            PropertyDef.objects.create(id=idmap[p["id"]], database=new_db, name=p["name"], type=p["type"],
                                       options=p.get("options") or [], config=remap(p.get("config") or {}),
                                       position=p.get("position", 0))
        for v in db.get("views", []):
            DbView.objects.create(database=new_db, name=v["name"], type=v["type"], config=remap(v.get("config") or {}),
                                  position=v.get("position", 0))
    for p in data.get("tag_properties", []):
        tag = ctx.tag(p["tag"]) if p.get("tag") else None
        PropertyDef.objects.create(id=idmap[p["id"]], tag=tag, name=p["name"], type=p["type"], options=p.get("options") or [])
    for d in doc_rows:
        doc = created[idmap[d["id"]]]
        if d.get("entry_of") and idmap.get(d["entry_of"]):
            doc.entry_of_id = idmap[d["entry_of"]]
            doc.save(update_fields=["entry_of"])
        if d.get("tags"):
            doc.tags.add(*[ctx.tag(t) for t in d["tags"]])
        for def_id, value in (d.get("values") or {}).items():
            if def_id in idmap:
                PropertyValue.objects.create(document=doc, definition_id=idmap[def_id], value=remap(value))
        blocks = []
        rows = d.get("blocks", [])
        ids = {b["id"] for b in rows}
        order, seen = [], set()
        by_id = {b["id"]: b for b in rows}

        def visit(b):
            if b["id"] in seen:
                return
            if b.get("parent") in ids:
                visit(by_id[b["parent"]])
            seen.add(b["id"])
            order.append(b)

        for b in rows:
            visit(b)
        for b in order:
            props = remap(b.get("props") or {})
            props.pop("task", None)
            blocks.append(Block(id=idmap[b["id"]], document=doc,
                                parent_id=idmap[b["parent"]] if b.get("parent") in ids else None,
                                position=b.get("position", 0), type=b["type"],
                                html=sanitize(remap(b.get("html", ""))) if b["type"] != "code" else b.get("html", ""),
                                props=props, collapsed=b.get("collapsed", False)))
        Block.objects.bulk_create(blocks)
        finish_doc(doc, blocks)
    return {"pages": len([d for d in doc_rows if not d.get("entry_of")]), "databases": len(data.get("databases", []))}


# ================================================================ Markdown out


class Exporter:
    """Renders documents to Markdown or HTML, collecting the attachments they use."""

    def __init__(self, attach_dir: str | None = None):
        self.attach_dir = attach_dir  # rewrite /media urls to this relative folder
        self.media: dict[str, str] = {}  # media url -> file name in the export
        self.titles = {str(i): t for i, t in Document.objects.values_list("id", "title")}

    def media_ref(self, url: str, depth: int = 0) -> str:
        if not self.attach_dir or not url.startswith("/media/"):
            return url
        name = self.media.setdefault(url, os.path.basename(url))
        return "../" * depth + f"{self.attach_dir}/{name}"

    # --- inline
    def md_inline(self, html: str) -> str:
        s = html or ""
        s = re.sub(r'<a [^>]*data-ref="tag:[^"]*"[^>]*>#?(.*?)</a>', lambda m: "#" + to_text(m.group(1)).replace(" ", "-"), s)
        s = re.sub(r'<a [^>]*data-ref="doc:([^"]*)"[^>]*>(.*?)</a>',
                   lambda m: f"[[{self.titles.get(m.group(1), to_text(m.group(2)))}]]", s)
        s = re.sub(r'<a [^>]*data-ref="block:[^"]*"[^>]*>(.*?)</a>', lambda m: to_text(m.group(1)), s)
        s = re.sub(r'<span [^>]*data-math="([^"]*)"[^>]*>.*?</span>', lambda m: f"${html_lib.unescape(m.group(1))}$", s)
        s = re.sub(r"<(b|strong)>(.*?)</\1>", r"**\2**", s)
        s = re.sub(r"<(i|em)>(.*?)</\1>", r"*\2*", s)
        s = re.sub(r"<(s|del|strike)>(.*?)</\1>", r"~~\2~~", s)
        s = re.sub(r"<code>(.*?)</code>", lambda m: f"`{html_lib.unescape(m.group(1))}`", s)
        s = re.sub(r"<mark[^>]*>(.*?)</mark>", r"==\1==", s)
        s = re.sub(r'<a [^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", s)
        s = s.replace("<br>", "  \n")
        s = re.sub(r"<[^>]+>", "", s)
        return html_lib.unescape(s)

    def md_blocks(self, blocks, depth=0, file_depth=0) -> list[str]:
        kids: dict = {}
        for b in blocks:
            kids.setdefault(b.parent_id, []).append(b)
        for v in kids.values():
            v.sort(key=lambda b: b.position)
        lines: list[str] = []

        def walk(parent, level, numbered_start=1):
            n = 0
            for b in kids.get(parent, []):
                pad = "  " * level
                t = b.type
                text = self.md_inline(b.html)
                p = b.props or {}
                if t == "numbered":
                    n += 1
                else:
                    n = 0
                if t in ("h1", "h2", "h3"):
                    lines.append(""); lines.append("#" * int(t[1]) + " " + text); lines.append("")
                elif t == "bullet" or t == "toggle":
                    lines.append(f"{pad}- {text}")
                elif t == "numbered":
                    lines.append(f"{pad}{n}. {text}")
                elif t == "todo":
                    lines.append(f"{pad}- [{'x' if p.get('checked') else ' '}] {text}")
                elif t == "quote":
                    lines.append(f"{pad}> {text}")
                elif t == "callout":
                    lines.append(f"{pad}> {p.get('icon', '💡')} {text}")
                elif t == "divider":
                    lines.append(f"{pad}---")
                elif t == "code":
                    lines.append(f"{pad}```{p.get('language', '')}")
                    lines.extend(pad + ln for ln in html_lib.unescape(b.html).split("\n"))
                    lines.append(f"{pad}```")
                elif t == "equation":
                    lines.append(f"{pad}$${p.get('tex', '')}$$")
                elif t == "table":
                    rows = p.get("rows") or []
                    if rows:
                        lines.append("")
                        for i, r in enumerate(rows):
                            lines.append("| " + " | ".join(self.md_inline(c).replace("|", "\\|") for c in r) + " |")
                            if i == 0:
                                lines.append("|" + "|".join(" --- " for _ in r) + "|")
                        lines.append("")
                elif t in ("image", "video", "audio", "file"):
                    url = self.media_ref(p.get("url", ""), file_depth)
                    label = p.get("caption") or p.get("name") or ""
                    lines.append(f"{pad}{'!' if t == 'image' else ''}[{label}]({url})")
                elif t == "bookmark":
                    lines.append(f"{pad}[{p.get('title') or p.get('url', '')}]({p.get('url', '')})")
                elif t == "embed":
                    target = p.get("doc") if p.get("kind") == "block" else p.get("target")
                    lines.append(f"{pad}![[{self.titles.get(str(target), 'Untitled')}]]")
                elif t == "database":
                    db = Database.objects.filter(id=p.get("database")).select_related("page").first()
                    lines.append(f"{pad}[[{db.page.title if db else 'Database'}]]")
                elif t == "synced":
                    pass
                else:
                    lines.append(f"{pad}{text}" if text else "")
                child_level = level if t in ("h1", "h2", "h3", "paragraph", "synced") else level + 1
                walk(b.id, child_level if t not in ("h1", "h2", "h3") else level)

        walk(None, depth)
        out, blank = [], False
        for ln in lines:
            if not ln.strip():
                if not blank and out:
                    out.append("")
                blank = True
            else:
                out.append(ln)
                blank = False
        return out

    def markdown(self, doc: Document, file_depth=0) -> str:
        head = ["---", f"title: {json.dumps(doc.title, ensure_ascii=False)}"]
        tags = [t.name for t in doc.tags.all()]
        if tags:
            head.append("tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]")
        from .views import doc_properties
        props = doc_properties(doc, [str(t.id) for t in doc.tags.all()])
        for d in props["defs"]:
            v = props["values"].get(d["id"])
            text = self.value_text(d, v)
            if text:
                head.append(f"{d['name']}: {json.dumps(text, ensure_ascii=False)}")
        head += [f"created: {doc.created_at.isoformat()}", f"updated: {doc.updated_at.isoformat()}", "---", ""]
        body = self.md_blocks(list(doc.blocks.all()), 0, file_depth)
        return "\n".join(head + [f"# {doc.icon + ' ' if doc.icon else ''}{doc.title or 'Untitled'}", ""] + body) + "\n"

    def value_text(self, d: dict, v) -> str:
        if v is None or v == "" or v == []:
            return ""
        t = d["type"]
        names = {o["id"]: o["name"] for o in d.get("options") or []}
        if t in ("select", "status"):
            return names.get(v, "")
        if t == "multi_select":
            return ", ".join(names.get(x, "") for x in v)
        if t == "relation":
            return ", ".join(self.titles.get(str(x), "") for x in v)
        if t == "boolean":
            return "true" if v else "false"
        if isinstance(v, dict) and "error" in v:
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v)

    # --- HTML
    def html_blocks(self, blocks, file_depth=0) -> str:
        kids: dict = {}
        for b in blocks:
            kids.setdefault(b.parent_id, []).append(b)
        for v in kids.values():
            v.sort(key=lambda b: b.position)

        def inline(h):
            h = re.sub(r'<a [^>]*data-ref="doc:([^"]*)"[^>]*>(.*?)</a>', lambda m: f'<a class="ref" href="#">{m.group(2)}</a>', h or "")
            h = re.sub(r'<span [^>]*data-math="([^"]*)"[^>]*>.*?</span>', lambda m: f'<span class="math">\\({m.group(1)}\\)</span>', h)
            return h

        def walk(parent) -> str:
            out = []
            items = kids.get(parent, [])
            i = 0
            while i < len(items):
                b = items[i]
                t, p = b.type, b.props or {}
                inner = walk(b.id)
                if t in ("bullet", "numbered", "todo", "toggle"):
                    tag = "ol" if t == "numbered" else "ul"
                    group = []
                    while i < len(items) and items[i].type == t:
                        x = items[i]
                        box = ""
                        if t == "todo":
                            box = f'<input type="checkbox" disabled{" checked" if (x.props or {}).get("checked") else ""}> '
                        group.append(f"<li>{box}{inline(x.html)}{walk(x.id)}</li>")
                        i += 1
                    cls = ' class="todo"' if t == "todo" else ""
                    out.append(f"<{tag}{cls}>{''.join(group)}</{tag}>")
                    continue
                if t in ("h1", "h2", "h3"):
                    out.append(f"<{t}>{inline(b.html)}</{t}>{inner}")
                elif t == "quote":
                    out.append(f"<blockquote>{inline(b.html)}{inner}</blockquote>")
                elif t == "callout":
                    out.append(f'<div class="callout"><span>{esc(p.get("icon", "💡"))}</span><div>{inline(b.html)}{inner}</div></div>')
                elif t == "divider":
                    out.append("<hr>")
                elif t == "code":
                    out.append(f"<pre><code>{b.html}</code></pre>")
                elif t == "equation":
                    out.append(f'<div class="eq">\\[{esc(p.get("tex", ""))}\\]</div>')
                elif t == "table":
                    rows = p.get("rows") or []
                    body = "".join(
                        "<tr>" + "".join(f"<{'th' if (j == 0 and p.get('header')) else 'td'}>{inline(c)}</{'th' if (j == 0 and p.get('header')) else 'td'}>" for c in r) + "</tr>"
                        for j, r in enumerate(rows))
                    out.append(f"<table>{body}</table>")
                elif t == "image":
                    out.append(f'<figure><img src="{esc(self.media_ref(p.get("url", ""), file_depth))}" alt="{esc(p.get("caption", ""))}">'
                               + (f"<figcaption>{esc(p['caption'])}</figcaption>" if p.get("caption") else "") + "</figure>")
                elif t in ("video", "audio"):
                    out.append(f'<{t} controls src="{esc(self.media_ref(p.get("url", ""), file_depth))}"></{t}>')
                elif t == "file":
                    out.append(f'<p><a href="{esc(self.media_ref(p.get("url", ""), file_depth))}">📎 {esc(p.get("name", "file"))}</a></p>')
                elif t == "bookmark":
                    out.append(f'<p><a href="{esc(p.get("url", ""))}">🔖 {esc(p.get("title") or p.get("url", ""))}</a></p>')
                elif t in ("embed", "database"):
                    title = "Embedded page"
                    if t == "embed":
                        target = p.get("doc") if p.get("kind") == "block" else p.get("target")
                        title = self.titles.get(str(target), title)
                    out.append(f'<p class="embed">↳ {esc(title)}</p>')
                elif t == "synced":
                    out.append(f'<div class="synced">{inner}</div>')
                    inner = ""
                else:
                    out.append(f"<p>{inline(b.html) or '&nbsp;'}</p>")
                if t not in ("h1", "h2", "h3", "quote", "callout", "synced"):
                    out.append(f'<div class="kids">{inner}</div>' if inner else "")
                i += 1
            return "".join(out)

        return walk(None)

    def html(self, doc: Document, print_mode=False, file_depth=0) -> str:
        tags = "".join(f'<span class="tag">#{esc(t.name)}</span>' for t in doc.tags.all())
        body = self.html_blocks(list(doc.blocks.all()), file_depth)
        auto = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300))</script>" if print_mode else ""
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(doc.title or 'Untitled')}</title>
<style>
body{{font:16px/1.6 -apple-system,'Segoe UI',Inter,system-ui,sans-serif;color:#222;max-width:760px;margin:40px auto;padding:0 20px}}
h1{{font-size:2em;margin:.2em 0 .1em}} .meta{{color:#888;font-size:.85em;margin-bottom:1.6em}} .tag{{margin-right:.6em;color:#a0621a}}
blockquote{{border-left:3px solid #ccc;margin:.6em 0;padding-left:1em;color:#555}} pre{{background:#f5f3ef;padding:12px;border-radius:6px;overflow:auto}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:.9em;background:#f5f3ef;padding:1px 4px;border-radius:3px}} pre code{{background:none;padding:0}}
table{{border-collapse:collapse;margin:.8em 0}} td,th{{border:1px solid #ddd;padding:5px 9px;text-align:left}} th{{background:#f5f3ef}}
img,video{{max-width:100%;border-radius:6px}} figcaption{{color:#777;font-size:.85em}} .callout{{display:flex;gap:.6em;background:#f5f3ef;padding:10px 14px;border-radius:6px;margin:.6em 0}}
ul.todo{{list-style:none;padding-left:1.2em}} .kids{{margin-left:1.5em}} .embed{{color:#888;font-style:italic}} .synced{{border:1px solid #e3c9a0;border-radius:6px;padding:4px 10px}}
a{{color:#a0621a}} mark{{background:#fde68a}} @media print{{body{{margin:0}} a{{color:inherit}}}}
</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" media="print" onload="this.media='all'">
</head><body><h1>{esc((doc.icon + ' ') if doc.icon else '')}{esc(doc.title or 'Untitled')}</h1>
<div class="meta">{tags} Last edited {doc.updated_at:%Y-%m-%d %H:%M}</div>
{body}{auto}</body></html>"""


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", (name or "Untitled").strip())[:120]
    return name or "Untitled"


def export_tree(root: Document | None, fmt: str = "md", include_children=True) -> tuple[bytes, str, str]:
    """Return (bytes, filename, mime). A single page without media is a plain file; otherwise a zip."""
    ex = Exporter(attach_dir="_attachments")
    if root and not include_children:
        docs = [root]
    elif root:
        from .views import subtree_ids
        ids = subtree_ids(root.id)
        docs = list(Document.objects.filter(id__in=ids, trashed_at__isnull=True, is_template=False))
    else:
        docs = list(Document.objects.filter(trashed_at__isnull=True, is_template=False))
    by_id = {d.id: d for d in docs}
    db_pages = {db.page_id: db for db in Database.objects.filter(page_id__in=by_id)}

    page_of_db = {db.id: page_id for page_id, db in db_pages.items()}

    def path_of(d: Document) -> list[str]:
        parts, cur, guard = [], d, 0
        while cur and guard < 50:
            guard += 1
            parts.insert(0, safe_name(cur.title))
            nxt = by_id.get(cur.parent_id) if cur.parent_id else by_id.get(page_of_db.get(cur.entry_of_id))
            cur = nxt if nxt is not cur else None
        return parts

    files: dict[str, bytes] = {}
    used_names: set[str] = set()
    for d in docs:
        parts = path_of(d)
        folder = "/".join(parts[:-1])
        stem = parts[-1]
        rel = (folder + "/" if folder else "") + stem
        n = 2
        while rel in used_names:
            rel = (folder + "/" if folder else "") + f"{stem} ({n})"
            n += 1
        used_names.add(rel)
        depth = rel.count("/")
        if fmt == "html":
            files[rel + ".html"] = ex.html(d, file_depth=depth).encode()
        else:
            files[rel + ".md"] = ex.markdown(d, file_depth=depth).encode()
        if d.id in db_pages:
            data, _, _ = export_database_csv(db_pages[d.id])
            files[rel + ".csv"] = data

    if len(files) == 1 and not ex.media:
        name, data = next(iter(files.items()))
        return data, os.path.basename(name), "text/html" if fmt == "html" else "text/markdown"
    buf = io.BytesIO()
    from django.conf import settings
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        for url, name in ex.media.items():
            path = os.path.join(settings.MEDIA_ROOT, url[len("/media/"):])
            if os.path.isfile(path):
                z.write(path, f"_attachments/{name}")
    base = safe_name(root.title) if root else "Kern workspace"
    return buf.getvalue(), f"{base}.zip", "application/zip"


def export_opml(root: Document) -> bytes:
    ex = Exporter()
    blocks = list(root.blocks.all())
    kids: dict = {}
    for b in blocks:
        kids.setdefault(b.parent_id, []).append(b)

    def walk(parent, el):
        for b in sorted(kids.get(parent, []), key=lambda b: b.position):
            text = ex.md_inline(b.html) if b.html else (b.props or {}).get("tex") or (b.props or {}).get("url") or ""
            o = ElementTree.SubElement(el, "outline", text=text)
            walk(b.id, o)

    opml = ElementTree.Element("opml", version="2.0")
    head = ElementTree.SubElement(opml, "head")
    ElementTree.SubElement(head, "title").text = root.title
    body = ElementTree.SubElement(opml, "body")
    walk(None, body)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(opml, encoding="utf-8")


# ======================================================================== CSV out


def export_database_csv(db: Database) -> tuple[bytes, str, str]:
    from . import dbcompute
    defs = list(db.properties.order_by("position"))
    rows = list(db.entries.filter(trashed_at__isnull=True, is_template=False).order_by("position"))
    values = dbcompute.compute(rows, defs) if rows else {}
    ex = Exporter()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name"] + [d.name for d in defs])
    for r in rows:
        vals = values.get(r.id, {})
        w.writerow([r.title] + [ex.value_text({"type": d.type, "options": d.options}, vals.get(str(d.id))) for d in defs])
    return buf.getvalue().encode("utf-8-sig"), f"{safe_name(db.page.title)}.csv", "text/csv"


def export_cards_csv(notes) -> tuple[bytes, str, str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Type", "Front", "Back", "Deck", "Source page"])
    for n in notes:
        w.writerow([n.kind, to_text(n.front), to_text(n.back), n.deck.name if n.deck_id else "Default",
                    n.document.title if n.document_id else ""])
    return buf.getvalue().encode("utf-8-sig"), "flashcards.csv", "text/csv"


# ========================================================================= Anki

_CLOZE = re.compile(r"\{\{(?:c(\d+)::)?(.+?)(?:::(.+?))?\}\}", re.S)


def to_anki_cloze(text: str) -> str:
    n = 0

    def repl(m):
        nonlocal n
        if m.group(1):
            num = int(m.group(1))
        else:
            n += 1
            num = n
        return "{{c%d::%s%s}}" % (num, m.group(2), f"::{m.group(3)}" if m.group(3) else "")

    return _CLOZE.sub(repl, text)


def export_anki(notes) -> tuple[bytes, str, str]:
    """A legacy-format .apkg (collection.anki2) that every Anki version can import."""
    from django.conf import settings
    now = int(time.time())
    ms = int(time.time() * 1000)
    m_basic, m_rev, m_cloze = ms, ms + 1, ms + 2
    decks = {1: {"id": 1, "name": "Default"}}
    deck_ids: dict = {}
    for d in Deck.objects.all():
        deck_ids[d.id] = ms + 10 + len(deck_ids)
        decks[deck_ids[d.id]] = {"id": deck_ids[d.id], "name": d.name}

    css = ".card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }\n.cloze { font-weight: bold; color: blue; }"

    def model(mid, name, mtype, fields, tmpls):
        return {
            "id": mid, "name": name, "type": mtype, "mod": now, "usn": -1, "sortf": 0, "did": 1, "css": css,
            "latexPre": "\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n\\usepackage[utf8]{inputenc}\n\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n\\setlength{\\parindent}{0in}\n\\begin{document}\n",
            "latexPost": "\\end{document}", "tags": [], "vers": [], "req": [[i, "any", [0]] for i in range(len(tmpls))],
            "flds": [{"name": f, "ord": i, "sticky": False, "rtl": False, "font": "Arial", "size": 20, "media": []}
                     for i, f in enumerate(fields)],
            "tmpls": [{"name": t[0], "ord": i, "qfmt": t[1], "afmt": t[2], "did": None, "bqfmt": "", "bafmt": ""}
                      for i, t in enumerate(tmpls)],
        }

    models = {
        str(m_basic): model(m_basic, "Basic (Kern)", 0, ["Front", "Back"],
                            [("Card 1", "{{Front}}", "{{FrontSide}}<hr id=answer>{{Back}}")]),
        str(m_rev): model(m_rev, "Basic and reversed (Kern)", 0, ["Front", "Back"],
                          [("Card 1", "{{Front}}", "{{FrontSide}}<hr id=answer>{{Back}}"),
                           ("Card 2", "{{Back}}", "{{FrontSide}}<hr id=answer>{{Front}}")]),
        str(m_cloze): model(m_cloze, "Cloze (Kern)", 1, ["Text", "Extra"],
                            [("Cloze", "{{cloze:Text}}", "{{cloze:Text}}<br>{{Extra}}")]),
    }
    deck_json = {
        str(k): {**v, "mod": now, "usn": -1, "lrnToday": [0, 0], "revToday": [0, 0], "newToday": [0, 0],
                 "timeToday": [0, 0], "collapsed": False, "desc": "", "dyn": 0, "conf": 1, "extendNew": 10,
                 "extendRev": 50}
        for k, v in decks.items()
    }
    dconf = {"1": {"id": 1, "name": "Default", "mod": 0, "usn": 0, "maxTaken": 60, "autoplay": True, "timer": 0,
                   "replayq": True, "dyn": False,
                   "new": {"delays": [1, 10], "ints": [1, 4, 7], "initialFactor": 2500, "order": 1, "perDay": 20, "bury": True, "separate": True},
                   "lapse": {"delays": [10], "mult": 0, "minInt": 1, "leechFails": 8, "leechAction": 0},
                   "rev": {"perDay": 200, "ease4": 1.3, "fuzz": 0.05, "ivlFct": 1, "maxIvl": 36500, "bury": True}}}
    conf = {"nextPos": 1, "estTimes": True, "activeDecks": [1], "sortType": "noteFld", "timeLim": 0,
            "sortBackwards": False, "addToCur": True, "curDeck": 1, "newBury": True, "newSpread": 0,
            "dueCounts": True, "curModel": str(m_basic), "collapseTime": 1200}

    media: dict[str, str] = {}

    def fix_media(h: str) -> str:
        def repl(m):
            url = m.group(1)
            if url.startswith("/media/"):
                name = os.path.basename(url)
                media[name] = os.path.join(settings.MEDIA_ROOT, url[len("/media/"):])
                return f'src="{name}"'
            return m.group(0)
        h = re.sub(r'<a [^>]*data-ref="[^"]*"[^>]*>(.*?)</a>', r"\1", h)
        h = re.sub(r'<span [^>]*data-math="([^"]*)"[^>]*>.*?</span>', lambda m: f"\\({m.group(1)}\\)", h)
        return re.sub(r'src="([^"]+)"', repl, h)

    tmp = tempfile.NamedTemporaryFile(suffix=".anki2", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.executescript("""
CREATE TABLE col (id integer primary key, crt integer not null, mod integer not null, scm integer not null, ver integer not null, dty integer not null, usn integer not null, ls integer not null, conf text not null, models text not null, decks text not null, dconf text not null, tags text not null);
CREATE TABLE notes (id integer primary key, guid text not null, mid integer not null, mod integer not null, usn integer not null, tags text not null, flds text not null, sfld integer not null, csum integer not null, flags integer not null, data text not null);
CREATE TABLE cards (id integer primary key, nid integer not null, did integer not null, ord integer not null, mod integer not null, usn integer not null, type integer not null, queue integer not null, due integer not null, ivl integer not null, factor integer not null, reps integer not null, lapses integer not null, left integer not null, odue integer not null, odid integer not null, flags integer not null, data text not null);
CREATE TABLE revlog (id integer primary key, cid integer not null, usn integer not null, ease integer not null, ivl integer not null, lastIvl integer not null, factor integer not null, time integer not null, type integer not null);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE INDEX ix_notes_usn on notes (usn); CREATE INDEX ix_cards_usn on cards (usn); CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_cards_nid on cards (nid); CREATE INDEX ix_cards_sched on cards (did, queue, due); CREATE INDEX ix_revlog_cid on revlog (cid); CREATE INDEX ix_notes_csum on notes (csum);
""")
    con.execute("INSERT INTO col VALUES (1,?,?,?,11,0,0,0,?,?,?,?,'{}')",
                (now - 86400, ms, ms, json.dumps(conf), json.dumps(models), json.dumps(deck_json), json.dumps(dconf)))
    nid = ms
    cid = ms
    pos = 0
    skipped = 0
    for n in notes:
        if n.kind == "occlusion":
            regions = n.regions or []
            pairs = [(f'<img src="{n.image}"><br>{n.front}<br>Region {i + 1}', r.get("label") or f"Region {i + 1}") for i, r in enumerate(regions)]
            if not pairs:
                skipped += 1
                continue
            entries = [(m_basic, [fix_media(a), fix_media(b)], 1) for a, b in pairs]
        elif n.kind == "cloze":
            entries = [(m_cloze, [fix_media(to_anki_cloze(n.front)), fix_media(n.back)], len(learning.cloze_ordinals(n.front)))]
        elif n.kind == "concept":
            entries = [(m_rev, [fix_media(n.front), fix_media(n.back)], 2)]
        else:
            entries = [(m_basic, [fix_media(n.front), fix_media(n.back)], 1)]
        did = deck_ids.get(n.deck_id, 1)
        for mid, fields, ncards in entries:
            nid += 1
            sfld = to_text(fields[0])
            csum = int(hashlib.sha1(sfld.encode()).hexdigest()[:8], 16)
            tags = " ".join(t.name.replace(" ", "_") for t in (n.document.tags.all() if n.document_id else []))
            con.execute("INSERT INTO notes VALUES (?,?,?,?,-1,?,?,?,?,0,'')",
                        (nid, uuid.uuid4().hex[:10], mid, now, f" {tags} " if tags else "", "\x1f".join(fields), sfld, csum))
            for ord_ in range(ncards):
                cid += 1
                pos += 1
                con.execute("INSERT INTO cards VALUES (?,?,?,?,?,-1,0,0,?,0,0,0,0,0,0,0,0,'')", (cid, nid, did, ord_, now, pos))
    con.commit()
    con.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp.name, "collection.anki2")
        mapping = {}
        for i, (name, path) in enumerate(media.items()):
            if os.path.isfile(path):
                z.write(path, str(i))
                mapping[str(i)] = name
        z.writestr("media", json.dumps(mapping))
    os.unlink(tmp.name)
    return buf.getvalue(), "Kern flashcards.apkg", "application/octet-stream"


def import_anki(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        coll = "collection.anki21" if "collection.anki21" in names else "collection.anki2" if "collection.anki2" in names else None
        if not coll:
            raise ValueError("This package uses Anki's newest format. In Anki, export again with “Support older Anki versions” ticked.")
        tmp = tempfile.NamedTemporaryFile(suffix=".anki2", delete=False)
        tmp.write(z.read(coll))
        tmp.close()
        media_map = {}
        if "media" in names:
            try:
                media_map = json.loads(z.read("media").decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                media_map = {}
        media_urls = {}
        for key, fname in media_map.items():
            if key in names:
                media_urls[fname] = save_file(fname, z.read(key))
    try:
        con = sqlite3.connect(tmp.name)
        models, decks = con.execute("SELECT models, decks FROM col").fetchone()
        models, decks = json.loads(models), json.loads(decks)
        if con.execute("SELECT count(*) FROM notes").fetchone()[0] == 1 and len(models) == 1 and "Please update" in (con.execute("SELECT flds FROM notes").fetchone()[0]):
            raise ValueError("This package uses Anki's newest format. In Anki, export again with “Support older Anki versions” ticked.")
        deck_of = dict(con.execute("SELECT nid, did FROM cards GROUP BY nid").fetchall())
        deck_cache: dict = {}

        def deck(did):
            name = (decks.get(str(did)) or {}).get("name") or "Default"
            if name == "Default":
                return None
            if name not in deck_cache:
                deck_cache[name] = Deck.objects.filter(name=name).first() or Deck.objects.create(name=name[:120])
            return deck_cache[name]

        def clean(h: str) -> str:
            h = re.sub(r'src="([^"]+)"', lambda m: f'src="{media_urls.get(html_lib.unescape(m.group(1)), m.group(1))}"', h)
            h = re.sub(r"\[sound:([^\]]+)\]", lambda m: f'<a href="{media_urls.get(m.group(1), "#")}">🔊 {esc(m.group(1))}</a>', h)
            h = re.sub(r"\\\((.+?)\\\)", lambda m: f'<span class="math" data-math="{esc(m.group(1))}" contenteditable="false">{esc(m.group(1))}</span>', h)
            return sanitize_card(h)

        count = 0
        for nid, mid, flds, tags in con.execute("SELECT id, mid, flds, tags FROM notes"):
            m = models.get(str(mid)) or {}
            fields = flds.split("\x1f")
            if m.get("type") == 1:
                n = CardNote(kind="cloze", front=clean(fields[0]), back=clean(fields[1]) if len(fields) > 1 else "")
            elif len(m.get("tmpls", [])) >= 2 and len(fields) >= 2:
                n = CardNote(kind="concept", front=clean(fields[0]), back=clean(fields[1]))
            else:
                back = "<br>".join(clean(f) for f in fields[1:] if f.strip())
                n = CardNote(kind="basic", front=clean(fields[0]), back=back)
            if not to_text(n.front).strip() and "<img" not in n.front:
                continue
            n.deck = deck(deck_of.get(nid))
            n.save()
            learning.ensure_cards(n)
            count += n.cards.count()
        con.close()
    finally:
        os.unlink(tmp.name)
    return {"cards": count}


def sanitize_card(h: str) -> str:
    import nh3
    from .text import INLINE_ATTRS, INLINE_TAGS
    return nh3.clean(h, tags=INLINE_TAGS | {"img", "div", "p", "ul", "ol", "li", "table", "tr", "td", "th", "tbody"},
                     attributes={**INLINE_ATTRS, "img": {"src", "alt", "width", "height"}}, link_rel=None,
                     url_schemes={"http", "https", "mailto", "tel"})
