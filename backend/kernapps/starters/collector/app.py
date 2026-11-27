"""Collector: numbers sent by devices and scripts, added up by day. Standard library only."""
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
DATA = Path(os.environ.get("APP_DATA_DIR", HERE / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "collector.db"


def token() -> str:
    if os.environ.get("INGEST_TOKEN"):
        return os.environ["INGEST_TOKEN"]
    f = DATA / "token"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(24))
    return f.read_text().strip()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS points (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, at TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS points_at ON points (at)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE / "static"), **kw)

    def log_message(self, fmt, *args):
        print(f"{self.command} {self.path.split('?')[0]} → {args[1] if len(args) > 1 else ''}", flush=True)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self.send_json({"ok": True})
        if path == "/api/summary":
            since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
            with db() as con:
                days = con.execute("""SELECT substr(at, 1, 10) AS day, metric, SUM(value) AS total FROM points
                                      WHERE at >= ? GROUP BY day, metric ORDER BY day""", (since,)).fetchall()
                sources = con.execute("""SELECT source, metric, SUM(value) AS total, COUNT(*) AS n, MAX(at) AS last
                                         FROM points GROUP BY source, metric ORDER BY last DESC""").fetchall()
            return self.send_json({"days": [dict(r) for r in days], "sources": [dict(r) for r in sources],
                                   "token": token()})
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/ingest":
            return self.send_json({"error": "Not found"}, 404)
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given, token()):
            return self.send_json({"error": "Wrong or missing token."}, 401)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(min(n, 1_000_000)) or b"{}")
        except ValueError:
            return self.send_json({"error": "Send JSON."}, 400)
        items = data if isinstance(data, list) else [data]
        rows = []
        for d in items[:1000]:
            try:
                rows.append((str(d.get("source") or "unknown")[:80], str(d.get("metric") or "value")[:80],
                             float(d["value"]), str(d.get("at") or now())[:32]))
            except (KeyError, TypeError, ValueError, AttributeError):
                return self.send_json({"error": "Each point needs a numeric value."}, 400)
        with db() as con:
            con.executemany("INSERT INTO points (source, metric, value, at) VALUES (?, ?, ?, ?)", rows)
        self.send_json({"stored": len(rows)}, 201)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Collector listening on port {port}", flush=True)
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), Handler).serve_forever()
