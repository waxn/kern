"""Shared pieces of the apps feature: folders, names, the manifest, how an app is built and started,
its environment and its settings. Used by the API (backend) and the worker (``manage.py apps_worker``).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.conf import settings

from kern import secretbox

# --------------------------------------------------------------------------- folders
#
# DATA_DIR/apps/<id>/
#   logs/            app.log (+ .1), deploy-<n>.log           written by the worker
#   src.git          mirror of a git URL source                worker
#   home/            HOME of the app's own user:               the app (and its builds)
#     data/          APP_DATA_DIR, kept across deploys
#     releases/<n>/  the files of deployment n
#     .cache/        pip / npm caches


def apps_root() -> Path:
    p = Path(getattr(settings, "KERN_APPS_DIR", "") or Path(settings.DATA_DIR) / "apps")
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_dir(app_id: int) -> Path:
    return apps_root() / str(int(app_id))


def logs_dir(app_id: int) -> Path:
    return app_dir(app_id) / "logs"


def home_dir(app_id: int) -> Path:
    return app_dir(app_id) / "home"


def data_dir(app_id: int) -> Path:
    return home_dir(app_id) / "data"


def releases_dir(app_id: int) -> Path:
    return home_dir(app_id) / "releases"


def release_dir(app_id: int, number: int) -> Path:
    return releases_dir(app_id) / str(int(number))


def app_log(app_id: int) -> Path:
    return logs_dir(app_id) / "app.log"


def deploy_log(app_id: int, number: int) -> Path:
    return logs_dir(app_id) / f"deploy-{int(number)}.log"


# ----------------------------------------------------------------------------- names

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")

# Paths Kern itself uses at the top level. An app can never take one of these. Keep in sync with
# frontend/src/routes (kernapps/tests.py checks it) and frontend/src/lib/kernRoutes.ts.
KERN_ROUTES = {
    "apps", "archive", "cards", "developer", "doc", "files", "git", "graph", "intelligence", "login",
    "mail", "review", "search", "settings", "signup", "tag", "tags", "tasks", "templates", "trash", "web",
}
RESERVED = KERN_ROUTES | {
    "api", "media", "pdfjs", "static", "assets", "admin", "auth", "setup", "health", "kern", "hooks",
    "logout", "new", "favicon", "robots", "sitemap", "service-worker", "manifest", "index", "well-known",
    "app", "home", "help", "docs", "account", "user", "users", "public", "www",
}


def valid_slug(slug: str) -> bool:
    return isinstance(slug, str) and bool(SLUG_RE.match(slug)) and "--" not in slug and slug not in RESERVED


def slug_problem(slug: str) -> str:
    if not isinstance(slug, str) or not slug:
        return "Choose a path for the app."
    if slug in RESERVED:
        return f"“/{slug}” is used by Kern itself. Pick another path."
    if not SLUG_RE.match(slug) or "--" in slug:
        return "Use 1–40 lowercase letters, digits and single dashes, starting and ending with a letter or digit."
    return ""


def suggest_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40].strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s or s in RESERVED:
        s = (s + "-app").strip("-")[:40] if s else "app"
    return s


def new_secret() -> str:
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- settings

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Set by Kern for every app; the app's own settings can't replace them.
OWN_ENV = {"PORT", "HOST", "HOME", "PATH", "APP_DATA_DIR", "KERN_BASE_PATH", "KERN_APP_SLUG", "KERN_APP_NAME",
           "KERN_APP_SECRET", "KERN_APP_ID"}
MAX_ENV = 100


def get_env(app) -> dict:
    if not app.env_enc:
        return {}
    try:
        data = json.loads(secretbox.decrypt(app.env_enc))
    except (secretbox.SecretBoxError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def set_env(app, values: dict) -> None:
    clean = {}
    for k, v in (values or {}).items():
        k = str(k).strip()
        if not ENV_NAME_RE.match(k):
            raise ValueError(f"“{k}” is not a valid variable name (letters, digits and _; not starting with a digit).")
        if k in OWN_ENV:
            raise ValueError(f"{k} is set by Kern and can't be changed.")
        clean[k] = str(v if v is not None else "")[:16_000]
    if len(clean) > MAX_ENV:
        raise ValueError(f"At most {MAX_ENV} variables.")
    app.env_enc = secretbox.encrypt(json.dumps(clean)) if clean else ""


def get_token(app) -> str:
    if not app.git_token_enc:
        return ""
    try:
        return secretbox.decrypt(app.git_token_enc)
    except secretbox.SecretBoxError:
        return ""


def set_token(app, token: str) -> None:
    app.git_token_enc = secretbox.encrypt(token) if token else ""


def clean_public_paths(paths) -> list[str]:
    out = []
    for p in paths or []:
        p = "/" + str(p or "").strip().strip("/")
        if p == "/" or len(p) > 200 or not re.match(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/-]+$", p) or ".." in p:
            continue
        if p not in out:
            out.append(p)
    return out[:20]


def path_is_public(app, sub: str) -> bool:
    """``sub`` is the path inside the app ("/api/x"). True when it falls under one of the public prefixes."""
    for p in app.public_paths or []:
        if sub == p or sub.startswith(p.rstrip("/") + "/"):
            return True
    return False


# ------------------------------------------------------------------- build and start

MANIFEST = ".kern/app.yml"
RUNTIME_NAMES = ("static", "python", "node", "command")


class PlanError(Exception):
    pass


@dataclass
class Plan:
    """How to build and run one release (from the app's settings, .kern/app.yml and the files)."""

    runtime: str
    build: list[str] = field(default_factory=list)  # shell commands, run in the app folder
    start: str = ""  # shell command; empty for static
    static_dir: str = ""  # static: folder (relative to the app folder) to serve
    health: str = ""  # path checked before traffic moves to a new release
    env: dict = field(default_factory=dict)  # defaults from the manifest
    notes: list[str] = field(default_factory=list)  # what was detected, for the deploy log

    def as_json(self) -> dict:
        return {"runtime": self.runtime, "build": self.build, "start": self.start, "static_dir": self.static_dir,
                "health": self.health, "env": self.env}

    @classmethod
    def from_json(cls, d: dict) -> "Plan":
        return cls(runtime=d.get("runtime", ""), build=list(d.get("build") or []), start=d.get("start", ""),
                   static_dir=d.get("static_dir", ""), health=d.get("health", ""), env=dict(d.get("env") or {}))


def read_manifest(root: Path) -> dict:
    p = root / MANIFEST
    if not p.is_file():
        p = root / ".kern" / "app.yaml"
        if not p.is_file():
            return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError as e:
        raise PlanError(f"{MANIFEST} is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise PlanError(f"{MANIFEST} must be a mapping (key: value lines).")
    return data


def _as_cmds(v) -> list[str]:
    if v in (None, ""):
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return [x for x in v if x.strip()]
    raise PlanError("build must be a command or a list of commands.")


def _safe_rel(root: Path, rel: str) -> str:
    rel = str(rel or "").strip().strip("/")
    if not rel:
        return ""
    p = (root / rel).resolve()
    if root.resolve() not in (p, *p.parents):
        raise PlanError(f"“{rel}” is outside the app.")
    return rel


def make_plan(app, root: Path) -> Plan:
    """Work out how to build and start the app whose files are in ``root``."""
    m = read_manifest(root)
    runtime = app.runtime or str(m.get("runtime") or "").strip().lower()
    if runtime and runtime not in RUNTIME_NAMES:
        raise PlanError(f"Unknown runtime “{runtime}”. Use one of: {', '.join(RUNTIME_NAMES)}.")
    notes = []
    pkg = {}
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except ValueError:
            raise PlanError("package.json is not valid JSON.")
        if not isinstance(pkg, dict):
            pkg = {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    py_entry = next((f for f in ("app.py", "main.py", "server.py") if (root / f).is_file()), "")
    has_py_deps = (root / "requirements.txt").is_file()

    if not runtime:
        if pkg:
            runtime = "node"
        elif py_entry or has_py_deps:
            runtime = "python"
        elif (root / "index.html").is_file():
            runtime = "static"
        else:
            raise PlanError("Kern could not tell how to run this app: there is no package.json, app.py/main.py/server.py "
                            f"or index.html. Add {MANIFEST} with a runtime and a start command.")
        notes.append(f"Detected a {runtime} app.")

    build = _as_cmds(app.build_cmd) if app.build_cmd else _as_cmds(m.get("build"))
    start = app.start_cmd or str(m.get("start") or "").strip()
    static_dir = _safe_rel(root, str(m.get("static") or ""))
    health = app.health_path or str(m.get("health") or "").strip()
    env = m.get("env") if isinstance(m.get("env"), dict) else {}
    env = {str(k): str(v) for k, v in env.items() if ENV_NAME_RE.match(str(k)) and str(k) not in OWN_ENV}

    if runtime == "node":
        if not build and "build" not in m:
            if pkg.get("dependencies") or pkg.get("devDependencies"):
                build.append("npm ci --no-audit --no-fund" if (root / "package-lock.json").is_file()
                             else "npm install --no-audit --no-fund")
            if "build" in scripts:
                build.append("npm run build")
        if not start:
            if "start" in scripts:
                start = "npm start"
            else:
                main = pkg.get("main") if isinstance(pkg.get("main"), str) else ""
                entry = next((f for f in (main, "server.js", "index.js", "app.js", "server.mjs", "index.mjs") if f and (root / f).is_file()), "")
                if entry:
                    start = f"node {shlex.quote(entry)}"
                elif "build" in scripts:
                    # A front-end project (Vite, React, ...): build it and serve the output.
                    runtime = "static"
                    notes.append("No start script: serving the build output as static files.")
                else:
                    raise PlanError("package.json has no start script and there is no server.js or index.js. "
                                    f"Add a start script or a start command in {MANIFEST}.")
    elif runtime == "python":
        if not build and "build" not in m and has_py_deps:
            build.append("python -m pip install --disable-pip-version-check -q -r requirements.txt")
        if not start:
            if not py_entry:
                raise PlanError(f"No app.py, main.py or server.py. Add a start command in {MANIFEST}.")
            start = f"python {py_entry}"
    elif runtime == "command":
        if not start:
            raise PlanError(f"A command app needs a start command (in the app's settings or {MANIFEST}).")
    elif runtime == "static":
        start = ""
    return Plan(runtime=runtime, build=build, start=start, static_dir=static_dir, health=health, env=env, notes=notes)


STATIC_GUESSES = ("", "dist", "build", "out", "public", "site", "www")


def static_root(release: Path, plan: Plan) -> Path:
    """The folder a static app is served from: the configured one, else the first that has an index.html."""
    if plan.static_dir:
        return release / plan.static_dir
    for d in STATIC_GUESSES:
        if (release / d / "index.html").is_file():
            return release / d
    return release


def app_env(app, port: int, release: Path, plan: Plan, isolated_home: Path) -> dict:
    """The complete environment of an app process. Built from nothing: nothing of Kern's own leaks in."""
    path = ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]
    if (release / ".venv").is_dir():
        path.insert(0, str(release / ".venv" / "bin"))
    if (release / "node_modules" / ".bin").is_dir():
        path.insert(0, str(release / "node_modules" / ".bin"))
    extra = os.environ.get("KERN_APPS_PATH", "")  # dev machines: where node/npm live
    if extra:
        path = [*extra.split(":"), *path]
    env = {**plan.env, **get_env(app)}
    env.update({
        "PORT": str(port),
        "HOST": "127.0.0.1",
        "HOME": str(isolated_home),
        "PATH": ":".join(path),
        "LANG": "C.UTF-8",
        "TZ": os.environ.get("TZ", "UTC"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NODE_ENV": env.get("NODE_ENV", "production"),
        "npm_config_cache": str(isolated_home / ".cache" / "npm"),
        "PIP_CACHE_DIR": str(isolated_home / ".cache" / "pip"),
        "APP_DATA_DIR": str(data_dir(app.id)),
        "KERN_BASE_PATH": f"/{app.slug}",
        "KERN_APP_SLUG": app.slug,
        "KERN_APP_NAME": app.name,
        "KERN_APP_ID": str(app.id),
        "KERN_APP_SECRET": app.secret,
    })
    if (release / ".venv").is_dir():
        env["VIRTUAL_ENV"] = str(release / ".venv")
    return env


def build_env(app, release: Path, isolated_home: Path) -> dict:
    """Environment of build commands: like the app's, without a port."""
    plan = Plan(runtime="")
    env = app_env(app, 0, release, plan, isolated_home)
    env.pop("PORT", None)
    env["NODE_ENV"] = "development"  # so npm installs devDependencies needed to build
    return env


# ------------------------------------------------------------------------ permissions


def can_use(user) -> bool:
    """May this user create and run apps? (Settings → Server → Apps.)"""
    if not (user and user.is_authenticated and user.is_active):
        return False
    from accounts import site

    mode = site.get_all().get("apps_access", "admins")
    if mode == "everyone":
        return True
    if mode == "admins":
        return bool(user.is_staff)
    return False


# --------------------------------------------------------------------------- control


def control_url() -> str:
    return os.environ.get("KERN_APPS_CONTROL", "http://127.0.0.1:8101").rstrip("/")


def control_token() -> str:
    """Shared between the backend and the worker through the data folder (mode 0600)."""
    p = apps_root() / ".control-token"
    if not p.exists():
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    return p.read_text().strip()
