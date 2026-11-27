"""The gateway: serves ``/<slug>/…`` for every app (the web container sends it every path that is not
one of Kern's own files or routes), plus the worker's control port for the backend.

For a path that is no app it answers 404 with ``X-Kern-Noapp: 1``, and the web container serves Kern's
page instead. Otherwise it checks who may open the app, then serves a static app's files or proxies
to the app's process (HTTP, streaming responses, server-sent events and WebSockets).

SECURITY: apps share Kern's address, so the gateway never lets Kern's session reach an app: the
session cookie is taken out of every request, an app can't set it, and the identity headers it
adds (``X-Kern-User``) come with the app's own secret so the app can tell they are real.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp import web
from django.conf import settings

from . import core
from .supervisor import Runtime, Supervisor, db

log = logging.getLogger("kern.apps")

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
       "transfer-encoding", "upgrade", "proxy-connection"}
STRIP_IN = {"x-kern-user", "x-kern-user-id", "x-kern-app-secret", "x-forwarded-prefix", "x-kern-control"}
SESSION_TTL = 15


class Sessions:
    """Kern session cookie → signed-in user, cached for a few seconds."""

    def __init__(self):
        self.cache: dict[str, tuple[float, dict | None]] = {}

    async def user(self, key: str | None) -> dict | None:
        if not key or len(key) > 100:
            return None
        hit = self.cache.get(key)
        if hit and time.monotonic() - hit[0] < SESSION_TTL:
            return hit[1]
        u = await db(self._lookup, key)
        if len(self.cache) > 2000:
            self.cache.clear()
        self.cache[key] = (time.monotonic(), u)
        return u

    @staticmethod
    def _lookup(key: str) -> dict | None:
        from django.contrib.auth import get_user
        from django.contrib.sessions.backends.db import SessionStore

        class Req:
            pass

        r = Req()
        r.session = SessionStore(session_key=key)
        try:
            u = get_user(r)
        except Exception:
            return None
        if not (u and u.is_authenticated and u.is_active):
            return None
        return {"id": u.id, "username": u.username, "admin": u.is_staff}


def _page(title: str, body: str, status: int, icon: str = "", actions: str = "") -> web.Response:
    """A small page in Kern's style (stopped app, sign-in needed…)."""
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{color-scheme:dark;--bg:#0f0f11;--text:#e7e5e0;--text2:#a5a39d;--line:#26262b;--accent:#e2a85a}}
@media (prefers-color-scheme:light){{:root{{color-scheme:light;--bg:#fcfbf9;--text:#23221f;--text2:#696761;--line:#e6e3dc;--accent:#b4721f}}}}
body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:var(--bg);color:var(--text);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;padding:24px;box-sizing:border-box}}
main{{max-width:420px;text-align:center}} .i{{font-size:40px;line-height:1;margin-bottom:14px}}
h1{{font-size:19px;font-weight:650;margin:0 0 6px}} p{{color:var(--text2);margin:0 0 18px}}
a.b{{display:inline-block;padding:7px 14px;border-radius:7px;background:var(--accent);color:#17130c;text-decoration:none;font-weight:550}}
a.g{{color:var(--text2);margin-left:12px}}
</style></head><body><main><div class="i">{html.escape(icon or '◇')}</div><h1>{html.escape(title)}</h1><p>{body}</p>{actions}</main></body></html>"""
    return web.Response(text=doc, status=status, content_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


def _no_app() -> web.Response:
    return web.Response(status=404, text="Not an app.", headers={"X-Kern-Noapp": "1", "Cache-Control": "no-store"})


class Gateway:
    def __init__(self, sup: Supervisor):
        self.sup = sup
        self.sessions = Sessions()
        self.client: aiohttp.ClientSession | None = None
        self.cookie_name = settings.SESSION_COOKIE_NAME

    async def start(self):
        self.client = aiohttp.ClientSession(
            auto_decompress=False, cookie_jar=aiohttp.DummyCookieJar(),
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None),
            connector=aiohttp.TCPConnector(limit=0, force_close=False))

    async def close(self):
        if self.client:
            await self.client.close()

    def app(self) -> web.Application:
        a = web.Application(client_max_size=1024 ** 3)
        a.router.add_route("POST", r"/_apps/hook/{id:\d+}/{secret}", self.hook)
        a.router.add_route("*", "/{tail:.*}", self.handle)
        return a

    # --------------------------------------------------------------------- hook

    async def hook(self, request: web.Request) -> web.Response:
        """Deploy hook (Settings → Source): POST from GitHub, Gitea, CI… queues a deployment."""
        from django.utils.crypto import constant_time_compare

        from . import deploy
        from .models import App

        app_id = int(request.match_info["id"])
        rt = self.sup.apps.get(app_id)
        if rt is None or not constant_time_compare(request.match_info["secret"], rt.app["hook_secret"]):
            return web.json_response({"error": "Unknown hook."}, status=404)

        def go():
            a = App.objects.filter(pk=app_id).first()
            return deploy.queue(a, "hook", "deploy hook").number if a else None

        n = await db(go)
        self.sup.wake.set()
        return web.json_response({"queued": n}, status=202)

    # ------------------------------------------------------------------- routing

    async def handle(self, request: web.Request) -> web.StreamResponse:
        path = request.raw_path.split("?", 1)[0]
        m = re.match(r"^/([a-z0-9][a-z0-9-]{0,39})(/.*)?$", path)
        if not m:
            return _no_app()
        slug, rest = m.group(1), m.group(2)
        rt = self.sup.find(slug)
        if rt is None:
            return _no_app()
        a = rt.app
        if rest is None:  # "/slug" → "/slug/" so relative links work
            qs = request.query_string
            raise web.HTTPPermanentRedirect(f"/{slug}/" + (f"?{qs}" if qs else ""))

        user = await self.sessions.user(request.cookies.get(self.cookie_name))
        if not self.allowed(a, user, rest):
            return self.refuse(request, a, user)

        inst = rt.current
        if inst is None or not inst.alive():
            return self.unavailable(rt, user)
        if inst.static_root is not None:
            return await self.static(request, inst.static_root, rest)
        upstream_path = rest if a["strip_prefix"] else path
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self.websocket(request, a, inst.port, upstream_path, user)
        return await self.proxy(request, a, inst.port, upstream_path, user)

    @staticmethod
    def allowed(a: dict, user: dict | None, rest: str) -> bool:
        if a["access"] == "public":
            return True
        for p in a["public_paths"]:
            if rest == p or rest.startswith(p.rstrip("/") + "/"):
                return True
        if user is None:
            return False
        return a["access"] == "users" or user["id"] == a["owner"]

    def refuse(self, request: web.Request, a: dict, user: dict | None) -> web.Response:
        wants_html = "text/html" in request.headers.get("Accept", "") and request.method in ("GET", "HEAD")
        if user is None:
            if wants_html:
                nxt = quote(request.raw_path, safe="/?=&")
                raise web.HTTPFound(f"/login?next={nxt}")
            return web.json_response({"error": "Sign in to Kern to use this app."}, status=401)
        if wants_html:
            return _page("This app is private", f"{html.escape(a['name'])} belongs to someone else.", 403, a["icon"],
                         '<a class="b" href="/">Back to Kern</a>')
        return web.json_response({"error": "This app is private."}, status=403)

    def unavailable(self, rt: Runtime, user: dict | None) -> web.Response:
        a = rt.app
        owner = user is not None and user["id"] == a["owner"]
        state = a.get("state", "")
        if rt.deploying is not None or state in ("building", "starting"):
            title, body = f"{a['name']} is starting", "It will be ready in a moment. This page reloads by itself."
            resp = _page(title, html.escape(body), 503, a["icon"],
                         f'<script>setTimeout(()=>location.reload(),2500)</script>')
            resp.headers["Retry-After"] = "3"
            return resp
        if state == "crashed":
            title, body = f"{a['name']} has stopped working", "It crashed. " + ("Check its log in Kern." if owner else "Try again later.")
        elif state in ("failed", "new") and a.get("live") is None:
            title, body = f"{a['name']} isn't deployed yet", "There's no working version of it yet." if not owner else "Its first deployment hasn't succeeded."
        else:
            title, body = f"{a['name']} is stopped", "Its owner has turned it off." if not owner else "You turned it off. Start it in Kern."
        actions = f'<a class="b" href="/apps/{a["slug"]}">Open in Kern</a>' if owner else ""
        return _page(title, html.escape(body), 503, a["icon"], actions)

    # -------------------------------------------------------------------- static

    async def static(self, request: web.Request, root: Path, rest: str) -> web.StreamResponse:
        if request.method not in ("GET", "HEAD"):
            return web.Response(status=405, text="Static app: only GET.")
        from urllib.parse import unquote

        rel = unquote(rest).lstrip("/")
        base = root.resolve()
        target = (base / rel).resolve() if rel else base
        if base not in (target, *target.parents):
            return web.Response(status=404, text="Not found.")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # Single-page apps: unknown paths without a file extension get index.html.
            if "." not in rel.rsplit("/", 1)[-1] and (base / "index.html").is_file():
                target = base / "index.html"
            else:
                return web.Response(status=404, text="Not found.")
        ctype, enc = mimetypes.guess_type(target.name)
        headers = {"Cache-Control": "no-cache" if target.suffix in (".html", ".htm", "") else "public, max-age=300"}
        return web.FileResponse(target, headers=headers)

    # --------------------------------------------------------------------- proxy

    def upstream_headers(self, request: web.Request, a: dict, user: dict | None) -> dict:
        h = {}
        for k, v in request.headers.items():
            lk = k.lower()
            if lk in HOP or lk in STRIP_IN or lk == "host" or lk.startswith("sec-websocket"):
                continue
            if lk == "cookie":
                kept = [c for c in v.split(";") if c.strip() and c.split("=", 1)[0].strip() not in (self.cookie_name, "csrftoken")]
                if not kept:
                    continue
                v = ";".join(kept).strip()
            h[k] = v
        peer = request.remote or ""
        fwd = request.headers.get("X-Forwarded-For")
        h["X-Forwarded-For"] = f"{fwd}, {peer}" if fwd else peer
        h["X-Forwarded-Proto"] = request.headers.get("X-Forwarded-Proto", request.scheme)
        h["X-Forwarded-Host"] = request.headers.get("X-Forwarded-Host", request.host)
        h["X-Forwarded-Prefix"] = f"/{a['slug']}"
        h["Host"] = request.host
        h["X-Kern-App-Secret"] = a["secret"]
        if user:
            h["X-Kern-User"] = user["username"]
            h["X-Kern-User-Id"] = str(user["id"])
        return h

    def rewrite_location(self, loc: str, a: dict, port: int) -> str:
        prefix = f"/{a['slug']}"
        for origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            if loc.startswith(origin):
                loc = loc[len(origin):] or "/"
                break
        if a["strip_prefix"] and loc.startswith("/") and not loc.startswith("//") and not (loc == prefix or loc.startswith(prefix + "/")):
            loc = prefix + loc
        return loc

    def rewrite_cookie(self, c: str, a: dict) -> str | None:
        name = c.split("=", 1)[0].strip()
        if name == self.cookie_name:
            return None  # an app may never set Kern's session
        if not a["strip_prefix"]:
            return c
        prefix = f"/{a['slug']}"

        def fix(m):
            p = m.group(2).strip()
            if p.startswith("/") and not (p == prefix or p.startswith(prefix + "/")):
                p = prefix + (p if p != "/" else "/")
            return f"{m.group(1)}{p}"

        if re.search(r";\s*path=", c, re.I):
            return re.sub(r"(;\s*path=)([^;]*)", fix, c, flags=re.I)
        return c + f"; Path={prefix}/"

    async def proxy(self, request: web.Request, a: dict, port: int, upath: str, user: dict | None) -> web.StreamResponse:
        qs = request.query_string
        url = f"http://127.0.0.1:{port}{upath}" + (f"?{qs}" if qs else "")
        headers = self.upstream_headers(request, a, user)
        data = request.content if request.body_exists else None
        try:
            up = await self.client.request(request.method, url, headers=headers, data=data, allow_redirects=False,
                                           skip_auto_headers=("Accept-Encoding", "User-Agent", "Content-Type"))
        except (aiohttp.ClientError, OSError) as e:
            log.info("app %s unreachable: %s", a["slug"], e)
            return _page(f"{a['name']} didn't answer", "The app is running but did not answer. Try again in a moment.",
                         502, a["icon"])
        try:
            resp = web.StreamResponse(status=up.status, reason=up.reason)
            for k, v in up.headers.items():
                lk = k.lower()
                if lk in HOP:
                    continue
                if lk == "location":
                    v = self.rewrite_location(v, a, port)
                elif lk == "set-cookie":
                    v = self.rewrite_cookie(v, a)
                    if v is None:
                        continue
                resp.headers.add(k, v)
            if "content-length" not in {k.lower() for k in up.headers}:
                resp.enable_chunked_encoding()
            await resp.prepare(request)
            if request.method != "HEAD":
                async for chunk in up.content.iter_any():
                    await resp.write(chunk)
            await resp.write_eof()
            return resp
        except (ConnectionResetError, aiohttp.ClientConnectionError, asyncio.CancelledError):
            raise
        finally:
            up.release()

    async def websocket(self, request: web.Request, a: dict, port: int, upath: str, user: dict | None):
        qs = request.query_string
        url = f"ws://127.0.0.1:{port}{upath}" + (f"?{qs}" if qs else "")
        protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
        headers = self.upstream_headers(request, a, user)
        headers.pop("Origin", None)
        try:
            upstream = await self.client.ws_connect(url, headers=headers, protocols=protocols, autoping=False,
                                                    max_msg_size=0)
        except (aiohttp.ClientError, OSError):
            return web.Response(status=502, text="The app did not accept the WebSocket.")
        server = web.WebSocketResponse(protocols=[upstream.protocol] if upstream.protocol else (), autoping=False,
                                       max_msg_size=0)
        await server.prepare(request)

        async def pump(src, dst):
            async for msg in src:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    await dst.ping(msg.data)
                elif msg.type == aiohttp.WSMsgType.PONG:
                    await dst.pong(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.ERROR):
                    break
            await dst.close()

        try:
            await asyncio.gather(pump(server, upstream), pump(upstream, server), return_exceptions=True)
        finally:
            await upstream.close()
            await server.close()
        return server


# ----------------------------------------------------------------------- control


class Control:
    """The backend's line to the worker: status numbers, kicks and restarts. Needs the control token."""

    def __init__(self, sup: Supervisor):
        self.sup = sup
        self.token = core.control_token()

    def app(self) -> web.Application:
        a = web.Application(middlewares=[self.auth])
        a.router.add_get("/status", self.status)
        a.router.add_get(r"/processes/{id:\d+}", self.processes)
        a.router.add_post("/kick", self.kick)
        a.router.add_post(r"/restart/{id:\d+}", self.restart)
        a.router.add_post(r"/request/{id:\d+}", self.request)
        return a

    @web.middleware
    async def auth(self, request, handler):
        from django.utils.crypto import constant_time_compare

        if not constant_time_compare(request.headers.get("X-Kern-Control", ""), self.token):
            return web.json_response({"error": "forbidden"}, status=403)
        return await handler(request)

    async def status(self, request):
        return web.json_response(self.sup.status())

    async def processes(self, request):
        """What runs for one app (its process group and children): pid, parent, command line, cpu, memory, age."""
        procs = await asyncio.to_thread(self.sup.processes, int(request.match_info["id"]))
        return web.json_response({"processes": procs})

    async def kick(self, request):
        self.sup.wake.set()
        return web.json_response({"ok": True})

    async def restart(self, request):
        await self.sup.restart(int(request.match_info["id"]))
        return web.json_response({"ok": True})

    async def request(self, request):
        """Make an HTTP request to the app as its owner would (the AI builder's test tool)."""
        rt = self.sup.apps.get(int(request.match_info["id"]))
        body = await request.json()
        out = await call_app(self.sup, rt, body.get("method", "GET"), body.get("path", "/"), body.get("body"),
                             body.get("headers") or {})
        return web.json_response(out)


async def call_app(sup: Supervisor, rt: Runtime | None, method: str, path: str, body=None, headers=None) -> dict:
    if rt is None:
        return {"error": "No such app."}
    inst = rt.current
    if inst is None or not inst.alive():
        return {"error": f"The app is not running (state: {rt.app.get('state')}). {rt.app.get('detail', '')}".strip()}
    path = "/" + str(path or "").lstrip("/")
    if inst.static_root is not None:
        rel = path.split("?")[0].lstrip("/") or "index.html"
        f = (inst.static_root / rel)
        if f.is_dir():
            f = f / "index.html"
        if not f.is_file():
            return {"status": 404, "body": "Not found."}
        return {"status": 200, "body": f.read_text(errors="replace")[:6000]}
    data = body if isinstance(body, (str, bytes)) or body is None else json.dumps(body)
    h = {str(k): str(v) for k, v in (headers or {}).items()}
    if isinstance(body, (dict, list)):
        h.setdefault("Content-Type", "application/json")
    h["X-Kern-App-Secret"] = rt.app["secret"]
    h["X-Forwarded-Prefix"] = f"/{rt.app['slug']}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.request(method.upper(), f"http://127.0.0.1:{inst.port}{path}", data=data, headers=h,
                                 allow_redirects=False) as r:
                text = await r.text(errors="replace")
                return {"status": r.status, "content_type": r.headers.get("Content-Type", ""),
                        "location": r.headers.get("Location", ""), "body": text[:6000],
                        "truncated": len(text) > 6000}
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
        return {"error": f"Request failed: {e}"}
