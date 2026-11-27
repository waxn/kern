"""Tracker: log numbers over time. Standard library only.

Kern starts this with PORT and APP_DATA_DIR set and serves it at /<path>/ (the prefix is removed
before requests get here, so routes start at "/").
"""
import json
import os
import sqlite3
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
DB = Path(os.environ.get("APP_DATA_DIR", HERE / "data")) / "tracker.db"
DB.parent.mkdir(parents=True, exist_ok=True)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY, subject TEXT NOT NULL, value REAL NOT NULL,
        unit TEXT NOT NULL DEFAULT '', day TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')""")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE / "static"), **kw)

    def log_message(self, fmt, *args):  # one short line per request in Kern's log
        print(f"{self.command} {self.path} → {args[1] if len(args) > 1 else ''}", flush=True)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json({"ok": True})
        if self.path.startswith("/api/entries"):
            with db() as con:
                rows = con.execute("SELECT * FROM entries ORDER BY day, id").fetchall()
            return self.send_json([dict(r) for r in rows])
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/entries":
            return self.send_json({"error": "Not found"}, 404)
        d = self.read_json()
        subject = str(d.get("subject") or "").strip()[:80]
        try:
            value = float(d.get("value"))
        except (TypeError, ValueError):
            return self.send_json({"error": "Enter a number."}, 400)
        if not subject:
            return self.send_json({"error": "Who or what is this for?"}, 400)
        day = str(d.get("day") or date.today().isoformat())[:10]
        with db() as con:
            cur = con.execute("INSERT INTO entries (subject, value, unit, day, note) VALUES (?, ?, ?, ?, ?)",
                              (subject, value, str(d.get("unit") or "")[:12], day, str(d.get("note") or "")[:300]))
            row = con.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
        self.send_json(dict(row), 201)

    def do_DELETE(self):
        if not self.path.startswith("/api/entries/"):
            return self.send_json({"error": "Not found"}, 404)
        with db() as con:
            con.execute("DELETE FROM entries WHERE id = ?", (self.path.rsplit("/", 1)[-1],))
        self.send_json({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Tracker listening on port {port}", flush=True)
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), Handler).serve_forever()
