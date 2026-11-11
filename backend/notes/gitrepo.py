"""Bare git repositories hosted by Kern: storage, safe git invocation and read helpers.

Repositories live in ``DATA_DIR/git/<name>.git``. Every git command goes through
:func:`git`, which ignores system/global config, disables hooks and never lets a
user-supplied value be parsed as an option (refs are resolved to a SHA first,
paths always come after ``--``).
"""
import json
from kern import tenancy
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
META_FILE = "kern.json"  # Kern's own metadata (last push), next to git's files
STATS_FILE = "kern-stats.json"  # cached stats, keyed by commit
MAX_BLOB = 1024 * 1024  # bytes of a file shown in the viewer
MAX_DIFF_LINES = 6000

# Applied to every git process, including `git http-backend` and the
# receive-pack it spawns: no hooks, no config from outside the repository.
SAFE_CONFIG = {
    "core.hooksPath": os.devnull,
    "core.fsmonitor": "false",
    "receive.fsckObjects": "true",
    "receive.denyNonFastForwards": "false",
    "http.receivepack": "true",
    "uploadpack.allowFilter": "true",
    "uploadpack.allowAnySHA1InWant": "false",
    "gc.auto": "0",
}


class GitError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def root() -> Path:
    p = tenancy.git_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def valid_name(name: str) -> bool:
    return (
        isinstance(name, str)
        and bool(NAME_RE.match(name))
        and ".." not in name
        and not name.lower().endswith(".git")
        and not name.endswith(".lock")
    )


def repo_path(name: str, must_exist=True) -> Path:
    if not valid_name(name):
        raise GitError("Invalid repository name.", 404 if must_exist else 400)
    base = root().resolve()
    p = (base / f"{name}.git").resolve()
    if p.parent != base:
        raise GitError("Invalid repository name.", 404)
    if must_exist and not (p / "HEAD").is_file():
        raise GitError("Repository not found.", 404)
    return p


def env(extra=None) -> dict:
    e = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root()),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": str(len(SAFE_CONFIG)),
    }
    for i, (k, v) in enumerate(SAFE_CONFIG.items()):
        e[f"GIT_CONFIG_KEY_{i}"] = k
        e[f"GIT_CONFIG_VALUE_{i}"] = v
    if extra:
        e.update(extra)
    return e


def git(path: Path, *args, check=True, input=None, timeout=60) -> bytes:
    cmd = ["git", f"--git-dir={path}", *args]
    try:
        r = subprocess.run(cmd, input=input, capture_output=True, env=env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitError("git took too long.", 504)
    if check and r.returncode != 0:
        raise GitError(r.stderr.decode(errors="replace").strip() or "git failed.", 400)
    return r.stdout


def text(path: Path, *args, **kw) -> str:
    return git(path, *args, **kw).decode("utf-8", errors="replace")


# ----------------------------------------------------------------- metadata


def read_meta(path: Path) -> dict:
    try:
        return json.loads((path / META_FILE).read_text())
    except (OSError, ValueError):
        return {}


def write_meta(path: Path, **kw) -> None:
    meta = read_meta(path) | kw
    tmp = path / (META_FILE + ".tmp")
    tmp.write_text(json.dumps(meta))
    os.replace(tmp, path / META_FILE)


def description(path: Path) -> str:
    try:
        d = (path / "description").read_text().strip()
    except OSError:
        return ""
    return "" if d.startswith("Unnamed repository;") else d


def set_description(path: Path, desc: str) -> None:
    (path / "description").write_text((desc or "").strip()[:500] + "\n")


def dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


# ---------------------------------------------------------------- lifecycle


def create(name: str, desc: str = "") -> Path:
    if not valid_name(name):
        raise GitError("Use 1–64 letters, digits, dots, dashes or underscores, starting with a letter or digit (no “.git” suffix).")
    path = repo_path(name, must_exist=False)
    if path.exists():
        raise GitError("A repository with that name already exists.", 409)
    tmp = path.with_name(f".{name}.creating")
    shutil.rmtree(tmp, ignore_errors=True)
    # Empty template: no sample hooks, no info/exclude.
    subprocess.run(
        ["git", "init", "--bare", "--quiet", "--template=", "--initial-branch=main", str(tmp)],
        check=True, capture_output=True, env=env(),
    )
    set_description(tmp, desc)
    os.replace(tmp, path)
    write_meta(path, created=now_iso())
    return path


def delete(name: str) -> None:
    path = repo_path(name)
    trash = path.with_name(f".{name}.deleting-{int(time.time())}")
    os.replace(path, trash)
    shutil.rmtree(trash, ignore_errors=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- refs


def head_branch(path: Path) -> str | None:
    r = git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).decode().strip()
    return r or None


def branches(path: Path) -> list[dict]:
    fmt = "%(refname:short)%1f%(objectname)%1f%(committerdate:iso-strict)%1f%(subject)%1f%(authorname)"
    out = []
    for line in text(path, "for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads").splitlines():
        n, sha, date, subj, author = (line.split("\x1f") + [""] * 5)[:5]
        out.append({"name": n, "sha": sha, "date": date, "subject": subj, "author": author})
    return out


def tags(path: Path) -> list[dict]:
    fmt = "%(refname:short)%1f%(objectname)%1f%(*objectname)%1f%(creatordate:iso-strict)%1f%(contents:subject)"
    out = []
    for line in text(path, "for-each-ref", "--sort=-creatordate", f"--format={fmt}", "refs/tags").splitlines():
        n, sha, peeled, date, subj = (line.split("\x1f") + [""] * 5)[:5]
        out.append({"name": n, "sha": peeled or sha, "date": date, "subject": subj})
    return out


def default_branch(path: Path, heads=None) -> str | None:
    heads = heads if heads is not None else [b["name"] for b in branches(path)]
    h = head_branch(path)
    if h in heads:
        return h
    for c in ("main", "master", "trunk", "develop"):
        if c in heads:
            return c
    return heads[0] if heads else None


def fix_head(path: Path) -> None:
    """After a push, point HEAD at a branch that exists (e.g. someone pushed `master` only)."""
    heads = [b["name"] for b in branches(path)]
    if not heads or head_branch(path) in heads:
        return
    target = default_branch(path, heads)
    if target:
        git(path, "symbolic-ref", "HEAD", f"refs/heads/{target}", check=False)


def resolve(path: Path, ref: str | None) -> str | None:
    """A branch, tag or SHA → full commit SHA. Never lets `ref` be read as an option."""
    if not ref:
        ref = default_branch(path)
        if not ref:
            return None
    if not isinstance(ref, str) or len(ref) > 250 or ref.startswith("-") or any(c in ref for c in "\0\n\r :~^?*[\\"):
        raise GitError("Invalid ref.", 404)
    for cand in (f"refs/heads/{ref}", f"refs/tags/{ref}", ref):
        r = git(path, "rev-parse", "--verify", "--quiet", "--end-of-options", cand + "^{commit}", check=False)
        sha = r.decode().strip()
        if SHA_RE.match(sha):
            return sha
    raise GitError("Unknown branch, tag or commit.", 404)


def clean_path(p: str | None) -> str:
    p = (p or "").strip("/")
    if not p:
        return ""
    parts = p.split("/")
    if any(s in ("", ".", "..") or "\0" in s for s in parts):
        raise GitError("Invalid path.", 404)
    return p


# ---------------------------------------------------------------- browsing


def summary(name: str, path: Path) -> dict:
    heads = branches(path)
    meta = read_meta(path)
    default = default_branch(path, [b["name"] for b in heads])
    last = next((b for b in heads if b["name"] == default), None)
    return {
        "name": name,
        "description": description(path),
        "size": dir_size(path),
        "empty": not heads,
        "default_branch": default,
        "branches": len(heads),
        "last_push": meta.get("last_push"),
        "created": meta.get("created"),
        "last_commit": last and {"sha": last["sha"], "date": last["date"], "subject": last["subject"], "author": last["author"]},
    }


def list_repos() -> list[dict]:
    out = []
    for p in sorted(root().iterdir()):
        if p.name.endswith(".git") and not p.name.startswith(".") and (p / "HEAD").is_file():
            name = p.name[:-4]
            if valid_name(name):
                out.append(summary(name, p))
    out.sort(key=lambda r: r["last_push"] or (r["last_commit"] or {}).get("date") or r["created"] or "", reverse=True)
    return out


def tree(path: Path, sha: str, sub: str) -> list[dict]:
    spec = f"{sha}:{sub}" if sub else f"{sha}^{{tree}}"
    kind = text(path, "cat-file", "-t", spec, check=False).strip()
    if kind != "tree":
        raise GitError("Not a folder.", 404)
    out = []
    raw = git(path, "ls-tree", "-z", "-l", "--end-of-options", spec)
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, _, fname = rec.partition(b"\t")
        mode, typ, obj, size = meta.decode().split(None, 3)
        n = fname.decode("utf-8", errors="replace")
        out.append({
            "name": n, "path": f"{sub}/{n}" if sub else n, "type": typ, "mode": mode,
            "size": int(size) if size.strip().isdigit() else None, "sha": obj,
        })
    order = {"tree": 0, "commit": 1, "blob": 2}
    out.sort(key=lambda e: (order.get(e["type"], 3), e["name"].lower()))
    return out


def blob(path: Path, sha: str, sub: str, limit=MAX_BLOB) -> dict:
    if not sub:
        raise GitError("Not a file.", 404)
    spec = f"{sha}:{sub}"
    if text(path, "cat-file", "-t", spec, check=False).strip() != "blob":
        raise GitError("File not found.", 404)
    size = int(text(path, "cat-file", "-s", spec).strip())
    data = git(path, "cat-file", "blob", spec)
    binary = b"\0" in data[:8000]
    out = {"path": sub, "size": size, "binary": binary, "truncated": False, "text": None}
    if not binary:
        out["truncated"] = len(data) > limit
        out["text"] = data[:limit].decode("utf-8", errors="replace")
        out["lines"] = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
    return out


def raw(path: Path, sha: str, sub: str) -> bytes:
    spec = f"{sha}:{clean_path(sub)}"
    if text(path, "cat-file", "-t", spec, check=False).strip() != "blob":
        raise GitError("File not found.", 404)
    return git(path, "cat-file", "blob", spec, timeout=120)


LOG_FMT = "%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%cI%x1f%s%x1f%b%x1e"


def parse_log(out: str) -> list[dict]:
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        f = rec.split("\x1f")
        if len(f) < 9:
            continue
        commits.append({
            "sha": f[0], "parents": f[1].split() if f[1] else [], "author": f[2], "email": f[3],
            "date": f[4], "committer": f[5], "committed": f[6], "subject": f[7], "body": f[8].strip(),
        })
    return commits


def log(path: Path, sha: str, sub: str = "", skip=0, limit=50) -> list[dict]:
    args = ["log", f"--format={LOG_FMT}", f"--skip={int(skip)}", f"-n{int(limit)}", "--end-of-options", sha]
    if sub:
        args += ["--", sub]
    return parse_log(text(path, *args))


def last_commit(path: Path, sha: str, sub: str) -> dict | None:
    r = log(path, sha, sub, limit=1)
    return r[0] if r else None


def commit(path: Path, sha: str) -> dict:
    c = parse_log(text(path, "show", "-s", f"--format={LOG_FMT}", "--end-of-options", sha))
    if not c:
        raise GitError("Commit not found.", 404)
    c = c[0]
    if c["parents"]:
        raw_diff = text(path, "diff", "--no-color", "--no-ext-diff", "-M", "--end-of-options", c["parents"][0], sha, timeout=120)
    else:
        raw_diff = text(path, "diff-tree", "-p", "-r", "-M", "--root", "--no-commit-id", "--no-color", "--no-ext-diff", "--end-of-options", sha, timeout=120)
    files, truncated = parse_diff(raw_diff)
    c["files"] = files
    c["truncated"] = truncated
    c["additions"] = sum(f["additions"] for f in files)
    c["deletions"] = sum(f["deletions"] for f in files)
    return c


def _unquote(p: str) -> str:
    if p.startswith('"') and p.endswith('"'):
        try:
            return p[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
        except (UnicodeError, ValueError):
            return p[1:-1]
    return p


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)")


def parse_diff(raw_diff: str) -> tuple[list[dict], bool]:
    files: list[dict] = []
    cur = None
    hunk = None
    budget = MAX_DIFF_LINES
    truncated = False
    o = n = 0
    for line in raw_diff.split("\n"):
        if line.startswith("diff --git "):
            cur = {"old_path": None, "new_path": None, "status": "modified", "binary": False,
                   "additions": 0, "deletions": 0, "hunks": [], "truncated": False}
            m = re.match(r'^diff --git (?:"?a/(.+?)"?) (?:"?b/(.+?)"?)$', line)
            if m:
                cur["old_path"], cur["new_path"] = _unquote(m.group(1)), _unquote(m.group(2))
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is None:
            if line.startswith("new file mode"):
                cur["status"] = "added"
            elif line.startswith("deleted file mode"):
                cur["status"] = "deleted"
            elif line.startswith("rename from "):
                cur["status"] = "renamed"; cur["old_path"] = _unquote(line[12:])
            elif line.startswith("rename to "):
                cur["new_path"] = _unquote(line[10:])
            elif line.startswith("Binary files "):
                cur["binary"] = True
            elif line.startswith("--- ") or line.startswith("+++ "):
                pass
        m = HUNK_RE.match(line)
        if m:
            o, n = int(m.group(1)), int(m.group(2))
            hunk = {"header": line, "lines": []}
            if budget > 0:
                cur["hunks"].append(hunk)
            else:
                cur["truncated"] = truncated = True
            continue
        if hunk is None or not line or line[0] not in "+- \\":
            continue
        t = line[0]
        if t == "+":
            cur["additions"] += 1
        elif t == "-":
            cur["deletions"] += 1
        if budget <= 0:
            cur["truncated"] = truncated = True
            continue
        budget -= 1
        if t == "\\":
            continue
        hunk["lines"].append({"t": t, "o": o if t != "+" else None, "n": n if t != "-" else None, "s": line[1:]})
        if t != "+":
            o += 1
        if t != "-":
            n += 1
    for f in files:
        if f["status"] == "added":
            f["old_path"] = None
        elif f["status"] == "deleted":
            f["new_path"] = None
    return files, truncated


# -------------------------------------------------------------------- stats

LANGS = {
    "py": ("Python", "#3572A5"), "pyi": ("Python", "#3572A5"), "js": ("JavaScript", "#f1e05a"),
    "mjs": ("JavaScript", "#f1e05a"), "cjs": ("JavaScript", "#f1e05a"), "jsx": ("JavaScript", "#f1e05a"),
    "ts": ("TypeScript", "#3178c6"), "tsx": ("TypeScript", "#3178c6"), "mts": ("TypeScript", "#3178c6"),
    "svelte": ("Svelte", "#ff3e00"), "vue": ("Vue", "#41b883"), "html": ("HTML", "#e34c26"),
    "htm": ("HTML", "#e34c26"), "css": ("CSS", "#663399"), "scss": ("SCSS", "#c6538c"),
    "sass": ("SCSS", "#c6538c"), "less": ("Less", "#1d365d"), "rs": ("Rust", "#dea584"),
    "go": ("Go", "#00ADD8"), "java": ("Java", "#b07219"), "kt": ("Kotlin", "#A97BFF"),
    "kts": ("Kotlin", "#A97BFF"), "swift": ("Swift", "#F05138"), "c": ("C", "#555555"),
    "h": ("C", "#555555"), "cc": ("C++", "#f34b7d"), "cpp": ("C++", "#f34b7d"), "cxx": ("C++", "#f34b7d"),
    "hpp": ("C++", "#f34b7d"), "hh": ("C++", "#f34b7d"), "cs": ("C#", "#178600"), "rb": ("Ruby", "#701516"),
    "php": ("PHP", "#4F5D95"), "sh": ("Shell", "#89e051"), "bash": ("Shell", "#89e051"),
    "zsh": ("Shell", "#89e051"), "fish": ("Shell", "#89e051"), "ps1": ("PowerShell", "#012456"),
    "lua": ("Lua", "#000080"), "dart": ("Dart", "#00B4AB"), "ex": ("Elixir", "#6e4a7e"),
    "exs": ("Elixir", "#6e4a7e"), "erl": ("Erlang", "#B83998"), "hs": ("Haskell", "#5e5086"),
    "ml": ("OCaml", "#ef7a08"), "clj": ("Clojure", "#db5855"), "scala": ("Scala", "#c22d40"),
    "r": ("R", "#198CE7"), "jl": ("Julia", "#a270ba"), "zig": ("Zig", "#ec915c"), "nim": ("Nim", "#ffc200"),
    "sql": ("SQL", "#e38c00"), "md": ("Markdown", "#083fa1"), "markdown": ("Markdown", "#083fa1"),
    "mdx": ("Markdown", "#083fa1"), "rst": ("reStructuredText", "#141414"), "tex": ("TeX", "#3D6117"),
    "json": ("JSON", "#292929"), "yaml": ("YAML", "#cb171e"), "yml": ("YAML", "#cb171e"),
    "toml": ("TOML", "#9c4221"), "xml": ("XML", "#0060ac"), "ini": ("INI", "#d1dbe0"),
    "dockerfile": ("Dockerfile", "#384d54"), "makefile": ("Makefile", "#427819"), "mk": ("Makefile", "#427819"),
    "nix": ("Nix", "#7e7eff"), "tf": ("HCL", "#844FBA"), "proto": ("Protocol Buffer", "#5a5a5a"),
    "graphql": ("GraphQL", "#e10098"), "gd": ("GDScript", "#355570"), "elm": ("Elm", "#60B5CC"),
    "vim": ("Vim Script", "#199f4b"), "el": ("Emacs Lisp", "#c065db"), "txt": ("Text", "#9a978f"),
}
SPECIAL = {"dockerfile": "dockerfile", "makefile": "makefile", "gnumakefile": "makefile", "containerfile": "dockerfile"}


def lang_of(fname: str):
    base = fname.rsplit("/", 1)[-1].lower()
    if base in SPECIAL:
        return LANGS[SPECIAL[base]]
    if "." not in base.strip("."):
        return None
    return LANGS.get(base.rsplit(".", 1)[-1])


def stats(name: str, path: Path, sha: str | None) -> dict:
    if not sha:
        return {"empty": True}
    cache_path = path / STATS_FILE
    try:
        cached = json.loads(cache_path.read_text())
        if cached.get("sha") == sha and cached.get("v") == 2:
            return cached
    except (OSError, ValueError):
        pass

    # Commits with per-author line counts (numstat), newest first, capped for huge histories.
    out = text(path, "log", "--format=\x1e%H\x1f%an\x1f%ae\x1f%aI", "--numstat", "--no-renames",
               "-n20000", "--end-of-options", sha, timeout=300)
    day_counts: dict[str, int] = {}
    month_counts: dict[str, int] = {}
    weekday_hour = [[0] * 24 for _ in range(7)]
    people: dict[str, dict] = {}
    total_commits = 0
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        f = head.split("\x1f")
        if len(f) < 4:
            continue
        total_commits += 1
        _h, an, ae, date = f
        try:
            dt = datetime.fromisoformat(date)
        except ValueError:
            continue
        day = dt.date().isoformat()
        day_counts[day] = day_counts.get(day, 0) + 1
        month_counts[day[:7]] = month_counts.get(day[:7], 0) + 1
        weekday_hour[dt.weekday()][dt.hour] += 1
        key = (ae or an).lower()
        p = people.setdefault(key, {"name": an, "email": ae, "commits": 0, "additions": 0, "deletions": 0,
                                    "first": date, "last": date})
        p["commits"] += 1
        p["first"] = date  # log is newest-first, so the final value is the oldest
        for ln in body.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3:
                a, d = parts[0], parts[1]
                p["additions"] += int(a) if a.isdigit() else 0
                p["deletions"] += int(d) if d.isdigit() else 0
    total_commits = int(text(path, "rev-list", "--count", "--end-of-options", sha).strip() or 0)

    # Files and languages at this commit (bytes from ls-tree, lines from the blobs themselves).
    entries = []
    for rec in git(path, "ls-tree", "-r", "-z", "-l", "--end-of-options", sha).split(b"\0"):
        if not rec:
            continue
        meta, _, fname = rec.partition(b"\t")
        mode, typ, obj, size = meta.decode().split(None, 3)
        if typ == "blob" and size.strip().isdigit():
            entries.append((fname.decode("utf-8", "replace"), obj, int(size)))
    langs: dict[str, dict] = {}
    total_lines = 0
    total_bytes = sum(e[2] for e in entries)
    budget = 200 * 1024 * 1024
    batch_in = b"".join(e[1].encode() + b"\n" for e in entries if e[2] <= 2 * 1024 * 1024)
    line_counts: dict[str, int] = {}
    if batch_in and total_bytes <= budget:
        proc = subprocess.run(["git", f"--git-dir={path}", "cat-file", "--batch"], input=batch_in,
                              capture_output=True, env=env(), timeout=300)
        data = proc.stdout
        i = 0
        while i < len(data):
            nl = data.index(b"\n", i)
            hdr = data[i:nl].split()
            if len(hdr) < 3:
                break
            size = int(hdr[2])
            content = data[nl + 1: nl + 1 + size]
            i = nl + 1 + size + 1
            if b"\0" not in content[:8000]:
                line_counts[hdr[0].decode()] = content.count(b"\n") + (0 if not content or content.endswith(b"\n") else 1)
    for fname, obj, size in entries:
        lines = line_counts.get(obj, 0)
        total_lines += lines
        lang = lang_of(fname)
        if not lang:
            continue
        l = langs.setdefault(lang[0], {"name": lang[0], "color": lang[1], "files": 0, "bytes": 0, "lines": 0})
        l["files"] += 1
        l["bytes"] += size
        l["lines"] += lines

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364 + (today.weekday() + 1) % 7)  # start on a Sunday, ~53 weeks
    heat = []
    d = start
    while d <= today:
        heat.append([d.isoformat(), day_counts.get(d.isoformat(), 0)])
        d += timedelta(days=1)
    months = sorted(month_counts.items())
    if months:  # fill gaps so the chart has a continuous axis
        y, m = map(int, months[0][0].split("-"))
        ey, em = map(int, max(months[-1][0], today.isoformat()[:7]).split("-"))
        filled = []
        while (y, m) <= (ey, em):
            k = f"{y:04d}-{m:02d}"
            filled.append([k, month_counts.get(k, 0)])
            m += 1
            if m > 12:
                y, m = y + 1, 1
        months = filled[-120:]
    contributors = sorted(people.values(), key=lambda p: (-p["commits"], p["name"].lower()))
    days_active = len(day_counts)
    result = {
        "v": 2, "sha": sha, "empty": False,
        "totals": {
            "commits": total_commits, "files": len(entries), "lines": total_lines, "bytes": total_bytes,
            "size": dir_size(path), "contributors": len(people), "branches": len(branches(path)),
            "tags": len(tags(path)), "active_days": days_active,
        },
        "first_commit": min(day_counts) if day_counts else None,
        "last_commit": max(day_counts) if day_counts else None,
        "heatmap": heat,
        "months": months,
        "punchcard": weekday_hour,
        "contributors": contributors[:25],
        "languages": sorted(langs.values(), key=lambda l: -l["bytes"]),
    }
    try:
        cache_path.write_text(json.dumps(result))
    except OSError:
        pass
    return result


def readme(path: Path, sha: str, sub: str = "") -> dict | None:
    try:
        entries = tree(path, sha, sub)
    except GitError:
        return None
    for e in entries:
        if e["type"] == "blob" and e["name"].lower() in ("readme.md", "readme.markdown", "readme", "readme.txt", "readme.rst"):
            b = blob(path, sha, e["path"], limit=256 * 1024)
            if not b["binary"]:
                return {"path": e["path"], "name": e["name"], "text": b["text"],
                        "markdown": e["name"].lower().endswith((".md", ".markdown"))}
    return None
