"""Read-only look at the SQLite files in an app's data folder (``APP_DATA_DIR``).

Used by the database explorer of the API and by the AI builder's ``query_db`` tool.

SECURITY. The app runs as its own user and controls everything in its data folder, so everything in
there is hostile input: a symlink to one of Kern's own databases, a hard link, a swapped data folder, a
``-wal`` file that is a symlink, a database with a schema that does evil things when read. So:

* :func:`safe_file` takes a path relative to the data folder and walks it component by component with
  ``lstat``: no symlinks anywhere (the data folder itself and its parents inside the app's folder
  included), the file is a regular file owned by the same user as the data folder (a hard link to a file of
  Kern's is owned by someone else), and so are its ``-wal``, ``-shm`` and ``-journal`` if they exist.
* :func:`connect` opens ``file:<quoted path>?mode=ro``, sets ``query_only`` and ``trusted_schema=OFF``
  and installs an *allow-list* authorizer: only reading is allowed (no ATTACH, no writes, no
  ``load_extension``, only a few read-only PRAGMAs), so even a statement that gets past the checks of
  :func:`check_sql` cannot change anything.
* Table and column names the caller sends are only ever used when they exist in the database, and then
  only as quoted identifiers. Values are bound, never interpolated.
* Every query has a time cap (progress handler) and row and size caps.

Known gap: between the check of the path and the moment SQLite opens it the app could swap the file for
a symlink. :func:`connect` closes it by checking that the file SQLite opened is the one that was checked
(Linux: ``/proc/self/fd``), but that check happens after the open, and a read-only open of a foreign
SQLite file changes nothing.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import stat
import time
from pathlib import Path
from urllib.parse import quote

from . import core

MAX_DEPTH = 4  # folders below the data folder that are searched
MAX_SCAN = 4000  # entries looked at while searching
MAX_FILES = 200
MAGIC = b"SQLite format 3\x00"
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db3", ".s3db", ".sdb")
SIDE = ("-wal", "-shm", "-journal")
TIME_CAP = 5.0  # seconds one request may spend inside SQLite
QUERY_ROWS = 500
ROWS_MAX = 200
CELL_TEXT = 2000
RESULT_BYTES = 8 * 1024 * 1024  # what one query may hand back, before it is cut off
SQL_MAX = 20_000

# The only PRAGMAs a query may run (all read-only).
PRAGMAS = {"table_info", "table_xinfo", "index_list", "index_info", "foreign_key_list"}

# sqlite3 authorizer action codes (the constants are not all exposed by every Python version).
_OK, _DENY = 0, 1
_READ, _SELECT, _FUNCTION, _RECURSIVE, _PRAGMA = 20, 21, 31, 33, 19


class DbError(ValueError):
    """Something the caller can fix (a bad name, a bad statement). ``status`` is the HTTP status."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# --------------------------------------------------------------------------- the path


def data_root(app_id: int) -> Path:
    """The app's data folder, after checking that it really is that folder (not a link to somewhere else)."""
    expected = Path(os.path.realpath(core.apps_root())) / str(int(app_id)) / "home" / "data"
    d = core.data_dir(app_id)
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        raise DbError("The app has no data folder yet.", 404)
    except OSError:
        raise DbError("The data folder cannot be read.", 404)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or Path(os.path.realpath(d)) != expected:
        raise DbError("The app's data folder is not a plain folder, so Kern will not open anything in it.", 403)
    return expected


def _plain_file(p: str, owner: int) -> os.stat_result:
    try:
        st = os.lstat(p)
    except OSError:
        raise DbError("No such file.", 404)
    if stat.S_ISLNK(st.st_mode):
        raise DbError("Symbolic links are not followed.", 403)
    if not stat.S_ISREG(st.st_mode):
        raise DbError("That is not a regular file.", 400)
    if st.st_uid != owner:
        raise DbError("That file does not belong to the app.", 403)
    return st


def safe_file(app_id: int, rel: str) -> tuple[str, os.stat_result]:
    """Absolute path of ``rel`` (inside the data folder) once it has passed every check, and its stat."""
    root = data_root(app_id)
    if not isinstance(rel, str) or not rel or len(rel) > 400 or "\0" in rel or "\\" in rel:
        raise DbError("Choose a database file.")
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise DbError("That is not a path inside the data folder.", 400)
    owner = os.lstat(root).st_uid
    cur = str(root)
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            raise DbError("No such file.", 404)
        if stat.S_ISLNK(st.st_mode):
            raise DbError("Symbolic links are not followed.", 403)
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            raise DbError("No such file.", 404)
    st = _plain_file(cur, owner)
    # Belt and braces: the real path is where we think it is.
    real = os.path.realpath(cur)
    if real != cur or os.path.commonpath([real, str(root)]) != str(root):
        raise DbError("That file is outside the data folder.", 403)
    for suffix in SIDE:
        if os.path.lexists(cur + suffix):
            _plain_file(cur + suffix, owner)
    return cur, st


def _sniff(path: str) -> bool:
    """True when the file starts like a SQLite database. Never blocks (no FIFOs) and never follows links."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        return os.read(fd, 16) == MAGIC
    except OSError:
        return False
    finally:
        os.close(fd)


def list_files(app_id: int) -> list[dict]:
    """SQLite files (and files that are named like one) under the data folder, at most MAX_DEPTH folders deep."""
    try:
        root = data_root(app_id)
    except DbError:
        return []
    owner = os.lstat(root).st_uid
    out, seen = [], 0
    stack = [(str(root), 0)]
    while stack and seen < MAX_SCAN and len(out) < MAX_FILES:
        base, depth = stack.pop()
        try:
            with os.scandir(base) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > MAX_SCAN:
                break
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                if depth < MAX_DEPTH:
                    stack.append((e.path, depth + 1))
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or e.name.endswith(SIDE):
                continue
            is_db = _sniff(e.path)
            if is_db or e.name.lower().endswith(DB_SUFFIXES):
                out.append({"path": os.path.relpath(e.path, root).replace(os.sep, "/"), "size": st.st_size, "is_sqlite": is_db})
    out.sort(key=lambda f: f["path"])
    return out


def pick_file(app_id: int, rel: str | None) -> str:
    """``rel``, or the only SQLite file there is."""
    if rel:
        return rel
    found = [f for f in list_files(app_id) if f["is_sqlite"]]
    if len(found) == 1:
        return found[0]["path"]
    if not found:
        raise DbError("This app has no SQLite database in its data folder.", 404)
    raise DbError("Choose a database file: " + ", ".join(f["path"] for f in found[:10]))


# --------------------------------------------------------------------------- the connection


def _authorizer(action, arg1, arg2, dbname, source):
    if action in (_SELECT, _RECURSIVE):
        return _OK
    if action == _READ:
        # The pragma_xxx() table functions bypass the PRAGMA check below.
        if isinstance(arg1, str) and arg1.lower().startswith("pragma_") and arg1.lower()[7:] not in PRAGMAS:
            return _DENY
        return _OK
    if action == _FUNCTION:
        return _DENY if str(arg2).lower() in ("load_extension", "fts3_tokenizer", "readfile", "writefile", "edit") else _OK
    if action == _PRAGMA:
        return _OK if str(arg1).lower() in PRAGMAS else _DENY
    return _DENY  # ATTACH, DETACH, every write, transactions, savepoints, ...


class Clock:
    """A deadline for the statements of one request (checked by SQLite every few thousand steps)."""

    def __init__(self, seconds: float | None = None):
        self.start = time.monotonic()
        self.deadline = self.start + (TIME_CAP if seconds is None else seconds)

    def expired(self) -> bool:
        return time.monotonic() > self.deadline

    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def __call__(self) -> int:  # progress handler: non-zero aborts the statement
        return 1 if self.expired() else 0


def _same_file_open(con: sqlite3.Connection, st: os.stat_result) -> bool:
    """Is the file SQLite has open the one that was checked? (Linux only; elsewhere there is nothing to ask.)"""
    fd_dir = "/proc/self/fd"
    if not os.path.isdir(fd_dir):
        return True
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()  # make SQLite open the file
    for name in os.listdir(fd_dir):
        try:
            fst = os.fstat(int(name))
        except (OSError, ValueError):
            continue
        if (fst.st_dev, fst.st_ino) == (st.st_dev, st.st_ino):
            return True
    return False


def connect(app_id: int, rel: str, clock: Clock | None = None, max_value: int = 64 * 1024 * 1024) -> sqlite3.Connection:
    path, st = safe_file(app_id, rel)
    if not _sniff(path):
        raise DbError("That file is not a SQLite database.")
    last = None
    for extra in ("", "&immutable=1"):  # a WAL database in a folder we cannot write to needs the second
        con = None
        try:
            con = sqlite3.connect(f"file:{quote(path)}?mode=ro{extra}", uri=True, timeout=1.0, check_same_thread=False)
            con.text_factory = lambda b: b.decode("utf-8", "replace")
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            if not _same_file_open(con, st):
                con.close()
                raise DbError("The file changed while it was being opened.", 409)
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, max_value)
            con.set_authorizer(_authorizer)
            if clock is not None:
                con.set_progress_handler(clock, 20000)
            return con
        except sqlite3.DatabaseError as e:
            last = e
            if con is not None:
                con.close()
            if "not a database" in str(e) or "malformed" in str(e):
                raise DbError("That file is not a readable SQLite database.")
    raise DbError(f"The database could not be opened ({last}).", 409)


def _sql_error(e: Exception) -> DbError:
    msg = str(e)
    if "interrupted" in msg:
        return DbError(f"The query took longer than {int(TIME_CAP)} seconds and was stopped.", 400)
    if "not authorized" in msg or "readonly" in msg:
        return DbError("Only reading is allowed here.", 403)
    if "too big" in msg:
        return DbError("A value is too large to show. Use length(column) or substr(column, 1, 200).")
    return DbError("SQL error: " + msg[:300])


# ---------------------------------------------------------------------------- values


def cell(v):
    """A value as JSON: BLOBs as {"blob": size}, long text cut at CELL_TEXT (the caller notes the cut: it is
    reported as ``truncated_cells``), no inf/nan. Every cell stays a string, number, null or {"blob"}."""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"blob": len(v)}
    if isinstance(v, str) and len(v) > CELL_TEXT:
        return v[:CELL_TEXT]
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    return v


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


_FIRST = re.compile(r"^(select|with|explain|pragma)\b", re.I)
_COMMENTS = re.compile(r"^(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)*", re.S)


def check_sql(sql) -> str:
    """The statement to run, or DbError. (A friendlier message only: the authorizer is what enforces it.)"""
    if not isinstance(sql, str) or not sql.strip():
        raise DbError("Write a SQL statement first.")
    if len(sql) > SQL_MAX:
        raise DbError(f"The statement is longer than {SQL_MAX} characters.")
    s = sql.strip().rstrip(";").strip()
    if not _FIRST.match(_COMMENTS.sub("", s, count=1)):
        raise DbError("Only SELECT, WITH, EXPLAIN and PRAGMA table_info statements can be run here (read-only).")
    return s


# ---------------------------------------------------------------------- structure


def _columns(con: sqlite3.Connection, table: str) -> list[dict]:
    rows = con.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    return [{"name": r[1], "type": r[2] or "", "pk": bool(r[5])} for r in rows]


def tables(con: sqlite3.Connection, clock: Clock) -> list[dict]:
    out = []
    rows = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
                       "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY type DESC, name LIMIT 500").fetchall()
    for name, kind in rows:
        try:
            cols = _columns(con, name)
        except sqlite3.DatabaseError:
            cols = []
        try:
            n = None if clock.expired() else con.execute(f"SELECT count(*) FROM {quote_ident(name)}").fetchone()[0]
        except sqlite3.DatabaseError:
            n = None  # a timeout, a virtual table whose module is missing, a view that no longer works
        t = {"name": name, "kind": kind, "rows": n or 0, "columns": cols}
        if n is None:
            t["rows_unknown"] = True  # "rows" is not a count then
        out.append(t)
    return out


def overview(app_id: int, rel: str | None) -> dict:
    """The answer of GET /db: the files, and the tables of the chosen one."""
    files = list_files(app_id)
    chosen = rel or None
    if chosen is None:
        sq = [f for f in files if f["is_sqlite"]]
        if len(sq) == 1:
            chosen = sq[0]["path"]
    out = {"files": files, "file": chosen, "tables": []}
    if chosen:
        clock = Clock()
        con = connect(app_id, chosen, clock)
        try:
            try:
                out["tables"] = tables(con, clock)
            except sqlite3.DatabaseError as e:
                raise _sql_error(e)
        finally:
            con.close()
    return out


# ---------------------------------------------------------------------------- rows


def table_rows(app_id: int, rel: str, table: str, offset=0, limit=50, order: str | None = None, direction: str = "asc") -> dict:
    """A page of one table or view. ``table`` and ``order`` must exist; they are used as quoted names."""
    offset = max(0, int(offset))
    limit = max(1, min(ROWS_MAX, int(limit)))
    if direction.lower() not in ("asc", "desc"):
        raise DbError("dir is asc or desc.")
    clock = Clock()
    con = connect(app_id, rel, clock)
    try:
        try:
            known = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            if table not in known:
                raise DbError("No such table.", 404)
            cols = [c["name"] for c in _columns(con, table)]
            if order and order not in cols:
                raise DbError("No such column to order by.")
            # BLOBs and long text are cut inside SQLite, so a 50 MB cell never reaches Python.
            parts = []
            for c in cols:
                q = quote_ident(c)
                parts.append(f"typeof({q}), CASE typeof({q}) WHEN 'blob' THEN length({q}) WHEN 'text' THEN substr({q}, 1, {CELL_TEXT}) ELSE {q} END, "
                             f"CASE typeof({q}) WHEN 'text' THEN length({q}) END")
            sql = f"SELECT {', '.join(parts) or '1'} FROM {quote_ident(table)}"
            if order:
                sql += f" ORDER BY {quote_ident(order)} {'DESC' if direction.lower() == 'desc' else 'ASC'}"
            total = con.execute(f"SELECT count(*) FROM {quote_ident(table)}").fetchone()[0]
            raw = con.execute(sql + " LIMIT ? OFFSET ?", (limit, offset)).fetchall() if cols else []
        except sqlite3.DatabaseError as e:
            raise _sql_error(e)
    finally:
        con.close()
    rows, cut = [], []
    for ri, r in enumerate(raw):
        row = []
        for i in range(len(cols)):
            kind, val, full = r[3 * i], r[3 * i + 1], r[3 * i + 2]
            if kind == "blob":
                row.append({"blob": val})
            else:
                if kind == "text" and full is not None and full > CELL_TEXT:
                    cut.append([ri, i, full])
                row.append(cell(val))
        rows.append(row)
    return {"columns": cols, "rows": rows, "total": total, "offset": offset, "limit": limit, "truncated_cells": cut}


# --------------------------------------------------------------------------- queries


def run_query(app_id: int, rel: str, sql, max_rows: int = QUERY_ROWS) -> dict:
    stmt = check_sql(sql)
    clock = Clock()
    con = connect(app_id, rel, clock, max_value=1_000_000)
    try:
        try:
            cur = con.execute(stmt)
            columns = [d[0] for d in cur.description or []]
            rows, cut, size, truncated = [], [], 0, False
            while True:
                r = cur.fetchone()
                if r is None:
                    break
                if len(rows) >= max_rows:
                    truncated = True
                    break
                out = [cell(v) for v in r]
                cut.extend([len(rows), i, len(v)] for i, v in enumerate(r) if isinstance(v, str) and len(v) > CELL_TEXT)
                size += sum(len(str(v)) for v in out)
                rows.append(out)
                if size > RESULT_BYTES:
                    truncated = True
                    break
        except (sqlite3.DatabaseError, sqlite3.Warning, sqlite3.ProgrammingError) as e:
            if "one statement" in str(e):
                raise DbError("Run one statement at a time.")
            raise _sql_error(e)
    finally:
        con.close()
    return {"columns": columns, "rows": rows, "truncated": truncated, "truncated_cells": cut,
            "seconds": round(clock.elapsed(), 3)}
