"""The AI builder: a conversation that writes and fixes one app.

Runs in the apps worker (not the web server) because a turn can take minutes: the model reads and
writes the app's files, deploys, reads the logs and tries the app over HTTP until it works. It uses
the owner's AI provider (Settings → AI), so it runs with the owner's tenant active.

File changes are collected during a turn and committed together when the model deploys (or when the
turn ends), as an ordinary commit on the app's branch: every change is in the repository's history.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from django.db import close_old_connections, connections
from django.utils import timezone

from kern import tenancy
from notes import ai

from . import core, deploy, source
from .models import App, BuilderChat, Deployment

log = logging.getLogger("kern.apps")

MAX_STEPS = 40
MAX_TOKENS = 64000
CONCURRENT = 2
MAX_HISTORY_BYTES = 1_500_000
DEPLOY_WAIT = deploy.BUILD_TIMEOUT + 120

SYSTEM = """You build and maintain one small web app that runs on the user's own server, inside Kern
(their self-hosted workspace). You work on the app's files through the tools, deploy it, and check that
it works. Be the careful, practical engineer who ships something that works today.

How apps run on Kern:
- Each app is served at /<path>/ on the user's server (the path is in the context). Kern removes that
  prefix before requests reach the app, so the server sees "/" and "/api/x". In HTML and JavaScript
  ALWAYS use relative URLs ("api/items", "style.css", never "/api/items"), so the app works under its path.
- A server app must listen on 127.0.0.1 and the port in the PORT environment variable.
- Keep data in the folder in APP_DATA_DIR (it survives deploys). SQLite is a good default.
- Runtimes: static (HTML/CSS/JS only, no server), python (python 3; app.py/main.py/server.py; a
  requirements.txt is installed into a venv), node (package.json; dependencies are installed with npm,
  "npm run build" runs if present, "npm start" or server.js starts it).
- Prefer no dependencies: Python's standard library (http.server, sqlite3, json) or Node's built-in
  modules are enough for most of these apps and never break on install.
- Add .kern/app.yml to say how to run it, e.g.:
    runtime: python
    start: python app.py
    health: /healthz      # a path that answers 200 once the app is ready
- Who can open the app is set in Kern (only the owner by default). Kern sends the signed-in Kern
  user's name in the X-Kern-User header, and X-Kern-App-Secret with the value of the KERN_APP_SECRET
  environment variable: trust X-Kern-User only when that secret matches.
- Paths that devices or scripts must reach without signing in to Kern (e.g. an ingest API) must be
  listed as public paths (update_settings), and the app must check its own token there (e.g. a
  bearer token from an environment variable the user sets in Kern, or one generated into APP_DATA_DIR).

How to work:
- Look before you change: list_files, then read what you need.
- Write complete files with write_file, or make small exact changes with edit_file.
- After changing files, call deploy. Read its result: if the build or start failed, fix the cause and
  deploy again. When it is live, try it with http_request (e.g. GET / and the API routes) and look at
  read_logs for errors.
- Make it look good: a clean, modern, mobile-friendly design with light and dark mode
  (prefers-color-scheme), system fonts, comfortable spacing, clear empty states.
- Keep it small and readable: a few files, no frameworks or build steps unless asked for.
- When done, reply briefly: what the app does now, anything the user has to do (e.g. set an
  environment variable), and what you'd suggest next. Don't paste the code back."""


def tool(name, description, props, required=()):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props, "required": list(required),
                             "additionalProperties": False}}


S = {"type": "string"}
TOOLS = [
    tool("list_files", "List the app's files (with changes not deployed yet).", {}),
    tool("read_file", "Read one file of the app.", {"path": S}, ["path"]),
    tool("write_file", "Create or replace a whole file.", {"path": S, "content": S}, ["path", "content"]),
    tool("edit_file", "Replace an exact piece of text in a file (it must occur exactly once).",
         {"path": S, "old": S, "new": S}, ["path", "old", "new"]),
    tool("delete_file", "Delete a file.", {"path": S}, ["path"]),
    tool("deploy", "Commit the changes made so far and deploy the app. Waits until it is live or has failed; "
                   "returns the result with the end of the build log and the app log.",
         {"message": {"type": "string", "description": "A short commit message: what changed."}}, ["message"]),
    tool("read_logs", "The newest lines of what the running app printed (stdout and stderr).",
         {"lines": {"type": "integer", "description": "How many lines (default 80)."}}),
    tool("http_request", "Send an HTTP request to the running app, as the owner would. The path is inside "
                         "the app (\"/\", \"/api/items\"). Returns status and the start of the body.",
         {"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": S,
          "body": {"description": "JSON value or text to send."},
          "headers": {"type": "object", "description": "Extra request headers."}}, ["method", "path"]),
    tool("update_settings", "Change the app's settings in Kern: description, icon (one emoji), public paths "
                            "(path prefixes reachable without signing in, e.g. [\"/api/ingest\"]). Only when "
                            "the app needs it or the user asks.",
         {"description": S, "icon": S, "public_paths": {"type": "array", "items": S}}),
]


class Stop(Exception):
    pass


class Session:
    """The tools, for one turn."""

    def __init__(self, app: App, chat: BuilderChat, call):
        self.app = app
        self.chat = chat
        self.call = call  # run a coroutine in the worker's loop (http_request)
        self.staged: dict[str, str | None] = {}
        self.actions: list[dict] = []
        self.last_save = 0.0

    # --------------------------------------------------------------- helpers

    def act(self, verb: str, detail: str = "", ok: bool | None = None):
        a = {"verb": verb, "detail": detail[:200]}
        if ok is not None:
            a["ok"] = ok
        self.actions.append(a)
        BuilderChat.objects.filter(pk=self.chat.pk).update(progress=self.actions, updated=timezone.now())

    def check_stop(self):
        if BuilderChat.objects.filter(pk=self.chat.pk, stop=True).exists():
            raise Stop()

    def _head(self):
        gd = source.git_dir(self.app, fetch=False)
        if not (gd / "HEAD").is_file():
            return gd, None
        try:
            return gd, source.resolve(self.app, gd)[0]
        except source.SourceError:
            return gd, None

    def _read(self, rel: str) -> str | None:
        rel = source.clean_rel(rel)
        if rel in self.staged:
            return self.staged[rel]
        gd, sha = self._head()
        if not sha:
            return None
        blob = source.read_file(self.app, gd, sha, rel)
        return None if blob is None else blob.decode("utf-8", errors="replace")

    # ----------------------------------------------------------------- tools

    def list_files(self):
        gd, sha = self._head()
        files = {f["path"]: f["size"] for f in (source.list_files(self.app, gd, sha) if sha else [])}
        for p, c in self.staged.items():
            if c is None:
                files.pop(p, None)
            else:
                files[p] = len(c.encode())
        self.act("Looked at the files", f"{len(files)} files")
        if not files:
            return "The app has no files yet."
        return "\n".join(f"{p}  ({n} bytes){'  [changed]' if p in self.staged else ''}" for p, n in sorted(files.items()))

    def read_file(self, path):
        c = self._read(path)
        if c is None:
            return json.dumps({"error": f"{path} does not exist."})
        self.act("Read", path)
        if len(c) > 200_000:
            return c[:200_000] + "\n…(cut off: the file is longer)"
        return c

    def write_file(self, path, content):
        rel = source.clean_rel(path)
        if not isinstance(content, str):
            return json.dumps({"error": "content must be text."})
        existed = self._read(rel) is not None
        self.staged[rel] = content
        self.act("Edited" if existed else "Created", rel)
        return f"Saved {rel} ({len(content.encode())} bytes). Not live until you deploy."

    def edit_file(self, path, old, new):
        rel = source.clean_rel(path)
        c = self._read(rel)
        if c is None:
            return json.dumps({"error": f"{rel} does not exist."})
        n = c.count(old)
        if n != 1:
            return json.dumps({"error": f"The text to replace occurs {n} times in {rel}; it must occur exactly once. "
                                        "Include more surrounding lines."})
        self.staged[rel] = c.replace(old, new, 1)
        self.act("Edited", rel)
        return f"Edited {rel}. Not live until you deploy."

    def delete_file(self, path):
        rel = source.clean_rel(path)
        if self._read(rel) is None:
            return json.dumps({"error": f"{rel} does not exist."})
        self.staged[rel] = None
        self.act("Deleted", rel)
        return f"Deleted {rel}. Not live until you deploy."

    def commit(self, message: str) -> str | None:
        if not self.staged:
            return None
        username = self._owner_name()
        sha = source.commit(self.app, dict(self.staged), message or "Changes by the AI builder",
                            f"{username} (AI builder)", "kern:ai")
        self.staged = {}
        return sha

    def _owner_name(self) -> str:
        from django.contrib.auth.models import User

        return User.objects.filter(pk=self.app.owner).values_list("username", flat=True).first() or "Kern"

    def deploy(self, message=""):
        sha = self.commit(message)
        if sha is None:
            gd, sha = self._head()
            if not sha:
                return json.dumps({"error": "There is nothing to deploy: write the app's files first."})
        dep = deploy.queue(self.app, "ai", "AI builder", sha=sha, subject=message or "")
        App.objects.filter(pk=self.app.pk).update(enabled=True)
        self.act("Deploying", f"#{dep.number}: {message}"[:200])
        start = time.monotonic()
        while time.monotonic() - start < DEPLOY_WAIT:
            self.check_stop()
            dep.refresh_from_db()
            if dep.status in ("live", "failed", "cancelled"):
                break
            time.sleep(1.5)
        build_log = deploy.tail(core.deploy_log(self.app.id, dep.number), 3500)
        ok = dep.status == "live"
        self.actions[-1] = {"verb": f"Deployed #{dep.number}" if ok else f"Deploy #{dep.number} failed",
                            "detail": message[:200] if ok else dep.error[:200], "ok": ok}
        BuilderChat.objects.filter(pk=self.chat.pk).update(progress=self.actions)
        out = {"deployment": dep.number, "status": dep.status, "error": dep.error, "build_log_end": build_log}
        if ok:
            time.sleep(1)
            out["app_log_end"] = deploy.tail(core.app_log(self.app.id), 2000)
            out["url_path"] = f"/{self.app.slug}/"
        elif dep.status not in ("failed", "cancelled"):
            out["note"] = "Still not finished; check again later with read_logs."
        return json.dumps(out)

    def read_logs(self, lines=80):
        lines = max(5, min(400, int(lines or 80)))
        text = deploy.tail(core.app_log(self.app.id), 200_000)
        self.act("Read the logs")
        return "\n".join(text.splitlines()[-lines:]) or "(The log is empty.)"

    def http_request(self, method, path, body=None, headers=None):
        from .gateway import call_app

        sup = self.call.sup
        rt = sup.apps.get(self.app.id)
        result = self.call(call_app(sup, rt, method, path, body, headers or {}))
        status = result.get("status")
        self.act("Tried", f"{method} {path} → {status if status else result.get('error', '')[:80]}",
                 ok=bool(status and status < 500) if status or result.get("error") else None)
        return json.dumps(result)

    def update_settings(self, description=None, icon=None, public_paths=None):
        changed = []
        if description is not None:
            self.app.description = str(description)[:300]
            changed.append("description")
        if icon:
            self.app.icon = str(icon)[:16]
            changed.append("icon")
        if public_paths is not None:
            self.app.public_paths = core.clean_public_paths(public_paths)
            changed.append("public paths: " + (", ".join(self.app.public_paths) or "none"))
        if changed:
            self.app.save(update_fields=["description", "icon", "public_paths", "updated"])
            deploy.kick()
        self.act("Changed settings", "; ".join(changed))
        return "Saved: " + ("; ".join(changed) or "nothing")


def _execute(sess: Session, name: str, args: dict) -> str:
    fn = getattr(sess, name, None) if name in {t["name"] for t in TOOLS} else None
    if fn is None:
        return json.dumps({"error": f"Unknown tool {name}."})
    try:
        r = fn(**(args or {}))
    except Stop:
        raise
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments: {e}"})
    except (source.SourceError, core.PlanError, ValueError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:  # keep the turn going; the model can react
        log.exception("builder tool %s failed", name)
        return json.dumps({"error": f"Kern hit an error: {e}"})
    return r if isinstance(r, str) else json.dumps(r, default=str)


def _context(app: App, sess: Session) -> str:
    dep = app.deployments.order_by("-number").first()
    gd, sha = sess._head()
    files = [f["path"] for f in source.list_files(app, gd, sha)] if sha else []
    lines = [
        f"App: {app.name} — served at /{app.slug}/ (Kern strips /{app.slug} before requests reach it: "
        f"{'yes' if app.strip_prefix else 'no'}).",
        f"Description: {app.description or '(none)'}",
        f"Who can open it: {dict(App._meta.get_field('access').choices)[app.access]}. Public paths: {', '.join(app.public_paths or []) or 'none'}.",
        f"State: {app.state}{' — ' + app.state_detail if app.state_detail else ''}.",
        f"Code: {'Kern repository ' + app.repo if app.source == 'kern' else app.git_url}, branch {app.branch}.",
        f"Environment variables set in Kern: {', '.join(sorted(core.get_env(app))) or 'none'}.",
        f"Files: {', '.join(files[:80]) or 'none yet'}{' …' if len(files) > 80 else ''}.",
    ]
    if dep:
        lines.append(f"Newest deployment: #{dep.number}, {dep.status}{' — ' + dep.error if dep.error else ''}.")
    lines.append(f"Today is {timezone.localdate():%A %Y-%m-%d}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------- loops


def _anthropic_loop(cfg, sess: Session, messages: list) -> str:
    import anthropic

    key = ai._get("ai_secret").get("api_key", "")
    client = anthropic.Anthropic(api_key=key, timeout=600.0, max_retries=2)
    use_fallbacks = cfg["model"] in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5-2", "claude-sonnet-5-5")
    reply = ""
    for _ in range(MAX_STEPS):
        sess.check_stop()
        kwargs = dict(model=cfg["model"], max_tokens=MAX_TOKENS, system=SYSTEM, tools=TOOLS, messages=messages)
        if cfg["model"].startswith(ai.EFFORT_MODELS):
            kwargs["output_config"] = {"effort": "high"}  # writing and debugging code repays the extra thought
        try:
            if use_fallbacks:
                with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs) as s:
                    msg = s.get_final_message()
            else:
                with client.messages.stream(**kwargs) as s:
                    msg = s.get_final_message()
        except anthropic.AuthenticationError:
            raise ai.AIError("Anthropic rejected the API key. Check it in Settings → AI.")
        except anthropic.NotFoundError:
            raise ai.AIError(f"Model “{cfg['model']}” was not found. Check Settings → AI.")
        except anthropic.RateLimitError:
            raise ai.AIError("Anthropic's rate limit was reached. Try again in a minute.")
        except anthropic.BadRequestError as e:
            raise ai.AIError(f"Anthropic refused the request: {e.message}")
        except anthropic.APIStatusError as e:
            raise ai.AIError(f"Anthropic returned an error ({e.status_code}). Try again shortly.")
        except anthropic.APIConnectionError:
            raise ai.AIError("Could not reach Anthropic.")
        # Keep the assistant turn exactly as returned (thinking blocks included) so the history stays valid.
        content = [b.model_dump(mode="json", exclude_none=True) for b in msg.content]
        messages.append({"role": "assistant", "content": content})
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if text:
            reply = text
        if msg.stop_reason == "refusal":
            return "I can't help with that request."
        if msg.stop_reason == "pause_turn":
            continue
        calls = [b for b in msg.content if b.type == "tool_use"]
        if msg.stop_reason == "max_tokens" and calls:
            # A cut-off tool call has incomplete input: say so instead of running it.
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c.id, "is_error": True,
                 "content": "Your answer was cut off before this call was complete. Write smaller files or use edit_file."}
                for c in calls]})
            continue
        if not calls:
            return reply
        results = []
        for c in calls:
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": _execute(sess, c.name, c.input or {})})
        messages.append({"role": "user", "content": results})
    return (reply + "\n\n(I stopped after many steps. Ask me to continue.)").strip()


def _openai_loop(cfg, sess: Session, messages: list) -> str:
    import urllib.error
    import urllib.request

    key = ai._get("ai_secret").get("api_key", "")
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
             for t in TOOLS]
    reply = ""
    for _ in range(MAX_STEPS):
        sess.check_stop()
        body = json.dumps({"model": cfg["model"], "messages": [{"role": "system", "content": SYSTEM}, *messages],
                           "tools": tools, "max_tokens": ai.MAX_TOKENS}).encode()
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
        req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as res:
                data = json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            raise ai.AIError(f"The provider returned an error ({e.code}). Does this model support tools?")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ai.AIError(f"Could not reach {cfg['base_url']} ({getattr(e, 'reason', e)}).")
        try:
            m = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ai.AIError("The provider sent an answer Kern could not read.")
        entry = {"role": "assistant", "content": m.get("content") or ""}
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        messages.append(entry)
        if m.get("content"):
            reply = m["content"]
        if not m.get("tool_calls"):
            return reply
        for call in m["tool_calls"]:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = None
            result = (json.dumps({"error": "The arguments were not valid JSON."}) if not isinstance(args, dict)
                      else _execute(sess, call["function"]["name"], args))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return (reply + "\n\n(I stopped after many steps. Ask me to continue.)").strip()


def _close_dangling(family: str, messages: list) -> None:
    """After a stop in the middle of tool calls, answer the open calls so the history stays valid."""
    last = messages[-1] if messages else None
    if not last or last.get("role") != "assistant":
        return
    if family == "anthropic":
        ids = [b["id"] for b in last.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if ids:
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": i, "is_error": True, "content": "Stopped by the user."} for i in ids]})
    else:
        for c in last.get("tool_calls") or []:
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": "Stopped by the user."})


def run_turn(chat_id: int, call) -> None:
    """One message of the conversation, start to end. Runs in a worker thread."""
    close_old_connections()
    try:
        chat = BuilderChat.objects.select_related("app").filter(pk=chat_id, status="queued").first()
        if chat is None:
            return
        BuilderChat.objects.filter(pk=chat.pk).update(status="running", progress=[])
        app = chat.app
        sess = Session(app, chat, call)
        text = chat.pending
        error = False
        with tenancy.use(app.owner):
            try:
                cfg = ai.config()
                if not ai.public_config()["configured"]:
                    raise ai.AIError("The AI assistant is not set up yet. Choose a provider in Settings → AI.")
                family = "anthropic" if cfg["provider"] == "anthropic" else "openai"
                history = chat.history if chat.provider == family else [
                    {"role": t["role"], "content": t["text"]} for t in chat.transcript[:-1] if t.get("text")]
                if len(json.dumps(history)) > MAX_HISTORY_BYTES:
                    # Too long to send again: carry on from the visible conversation only.
                    history = [{"role": t["role"], "content": t["text"]} for t in chat.transcript[-20:-1] if t.get("text")]
                messages = [*history, {"role": "user", "content": f"<context>\n{_context(app, sess)}\n</context>\n\n{text}"}]
                loop = _anthropic_loop if family == "anthropic" else _openai_loop
                try:
                    reply = loop(cfg, sess, messages)
                except Stop:
                    reply = "Stopped."
                    _close_dangling(family, messages)
                if sess.staged:
                    # Changes the model made but did not deploy: keep them (a commit; auto-deploy picks it up).
                    try:
                        sess.commit("Changes by the AI builder")
                        sess.act("Saved the changes", "committed; deploying" if app.auto_deploy else "committed")
                    except source.SourceError as e:
                        sess.act("Could not save the changes", str(e), ok=False)
                chat.history = messages
                chat.provider = family
            except ai.AIError as e:
                reply, error = str(e), True
            except Exception as e:
                log.exception("builder turn failed")
                reply, error = f"Something went wrong: {e}", True
        turn = {"role": "assistant", "text": reply or "Done.", "actions": sess.actions, "at": timezone.now().isoformat()}
        if error:
            turn["error"] = True
        BuilderChat.objects.filter(pk=chat.pk).update(
            transcript=[*chat.transcript, turn], history=chat.history, provider=chat.provider,
            status="idle", pending="", progress=[], stop=False, updated=timezone.now())
    finally:
        connections.close_all()


class Builder:
    """Picks up queued messages and runs them, a few at a time."""

    def __init__(self, sup):
        self.sup = sup
        self.running: dict[int, asyncio.Task] = {}
        self.recovered = False

    async def poll(self):
        from .supervisor import db

        if not self.recovered:
            await db(self._recover)
            self.recovered = True
        if len(self.running) >= CONCURRENT:
            return
        ids = await db(lambda: list(BuilderChat.objects.filter(status="queued").order_by("updated").values_list("pk", flat=True)))
        loop = asyncio.get_running_loop()

        def call(coro):
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=60)

        call.sup = self.sup
        for pk in ids:
            if pk in self.running or len(self.running) >= CONCURRENT:
                continue
            task = asyncio.create_task(asyncio.to_thread(run_turn, pk, call))
            self.running[pk] = task
            task.add_done_callback(lambda _t, pk=pk: (self.running.pop(pk, None), self.sup.wake.set()))

    @staticmethod
    def _recover():
        for c in BuilderChat.objects.filter(status="running"):
            c.transcript = [*c.transcript, {"role": "assistant", "text": "(Interrupted: the apps service restarted. Send the message again.)",
                                            "error": True, "at": timezone.now().isoformat()}]
            c.status, c.pending, c.progress = "idle", "", []
            c.save()

    async def shutdown(self):
        for pk in list(self.running):
            await asyncio.to_thread(lambda: BuilderChat.objects.filter(pk=pk).update(stop=True))
