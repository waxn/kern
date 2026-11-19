"""Kern CI: reading and validating a pipeline file (``.kern/ci.yml``).

Pure functions, no database: :func:`parse` turns YAML text into a normalized dict or raises
:class:`PipelineError` with a message meant for the person who wrote the file (it is shown as the
error of a failed run). See docs/git-ci.md for the format.
"""
from __future__ import annotations

import os
import re

import yaml

PIPELINE_FILES = (".kern/ci.yml", ".kern/ci.yaml")
MAX_FILE_BYTES = 256 * 1024
MAX_JOBS = 50
MAX_STEPS = 200
MAX_PATTERNS = 50

JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")

TOP_KEYS = {"on", "image", "env", "timeout", "jobs"}
JOB_KEYS = {"image", "env", "needs", "if", "secrets", "steps", "artifacts", "timeout", "name"}
STEP_KEYS = {"name", "run", "env", "timeout"}


class PipelineError(ValueError):
    pass


def limits() -> dict:
    """Timeouts in seconds, read from the environment every time (so they can be changed without a
    restart in tests)."""
    def num(name, default):
        try:
            v = float(os.environ.get(name, default))
        except ValueError:
            v = float(default)
        return v if v > 0 else float(default)

    return {
        "default": num("KERN_CI_DEFAULT_TIMEOUT_MIN", 30) * 60,
        "max": num("KERN_CI_MAX_TIMEOUT_MIN", 360) * 60,
    }


def default_image() -> str:
    img = os.environ.get("KERN_CI_DEFAULT_IMAGE", "").strip()
    return img if IMAGE_RE.match(img) else "debian:stable-slim"


# ------------------------------------------------------------------ globs


def glob_regex(pattern: str) -> re.Pattern:
    """Path glob: ``*`` and ``?`` stay inside one folder, ``**`` crosses folders."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z", re.S)


def matches_path(pattern_re: re.Pattern, rel: str) -> bool:
    """True when the file, or any folder above it, matches (so ``dist`` collects ``dist/a/b``)."""
    parts = rel.split("/")
    return any(pattern_re.match("/".join(parts[:i])) for i in range(1, len(parts) + 1))


def ref_match(patterns: list[str], name: str) -> bool:
    """Branch/tag name against globs where ``*`` matches anything, slashes included."""
    for p in patterns:
        rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in p)
        if re.fullmatch(rx, name, re.S):
            return True
    return False


# ---------------------------------------------------------------- parsing


def _str_list(v, where, *, allow_empty=True, maxlen=200) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise PipelineError(f"{where} must be a list of non-empty strings.")
    if len(v) > MAX_PATTERNS:
        raise PipelineError(f"{where} may have at most {MAX_PATTERNS} entries.")
    out = []
    for x in v:
        x = x.strip()
        if len(x) > maxlen or "\0" in x or "\n" in x:
            raise PipelineError(f"{where}: invalid entry {x[:40]!r}.")
        out.append(x)
    if not out and not allow_empty:
        raise PipelineError(f"{where} must not be empty.")
    return out


def _env(v, where) -> dict[str, str]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise PipelineError(f"{where} must be a mapping of NAME: value.")
    out = {}
    for k, val in v.items():
        k = str(k)
        if not ENV_RE.match(k):
            raise PipelineError(f"{where}: {k!r} is not a valid variable name.")
        if k.startswith("KERN_"):
            raise PipelineError(f"{where}: {k} is reserved (KERN_* variables are set by Kern).")
        if isinstance(val, (dict, list)):
            raise PipelineError(f"{where}.{k} must be a single value.")
        out[k] = "" if val is None else ("true" if val is True else "false" if val is False else str(val))
    return out


def _timeout(v, where):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise PipelineError(f"{where} must be a positive number of minutes.")
    return float(v)


def _image(v, where):
    if v is None:
        return None
    if not isinstance(v, str) or not IMAGE_RE.match(v.strip()):
        raise PipelineError(f"{where} is not a valid image name.")
    return v.strip()


def _unknown(d: dict, allowed: set, where: str):
    for k in d:
        if k not in allowed:
            raise PipelineError(f"{where}: unknown key {str(k)!r} (allowed: {', '.join(sorted(allowed))}).")


def _parse_on(v) -> dict:
    on = {"push": {"branches": ["*"], "tags": []}, "manual": True}
    if v is None:
        return on
    if isinstance(v, str):
        v = [v]
    if isinstance(v, list):
        names = _str_list(v, "on")
        for n in names:
            if n not in ("push", "manual"):
                raise PipelineError(f"on: unknown trigger {n!r} (use push or manual).")
        on["push"] = on["push"] if "push" in names else None
        on["manual"] = "manual" in names
        return on
    if not isinstance(v, dict):
        raise PipelineError("on must be a mapping (push, manual).")
    _unknown(v, {"push", "manual"}, "on")
    if "manual" in v:
        if not isinstance(v["manual"], bool):
            raise PipelineError("on.manual must be true or false.")
        on["manual"] = v["manual"]
    if "push" in v:
        p = v["push"]
        if p is False:
            on["push"] = None
        elif p is None or p is True:
            pass
        elif isinstance(p, dict):
            _unknown(p, {"branches", "tags"}, "on.push")
            branches = _str_list(p.get("branches"), "on.push.branches") if "branches" in p else ["*"]
            tags = _str_list(p.get("tags"), "on.push.tags")
            on["push"] = {"branches": branches, "tags": tags}
        else:
            raise PipelineError("on.push must be a mapping with branches and tags.")
    return on


def _parse_if(v, where):
    if v is None:
        return None
    if not isinstance(v, dict) or not v:
        raise PipelineError(f"{where} must be a mapping like {{branch: main}} or {{tag: \"v*\"}}.")
    _unknown(v, {"branch", "tag"}, where)
    cond = {k: _str_list(v[k], f"{where}.{k}", allow_empty=False) for k in ("branch", "tag") if k in v}
    return cond


def _parse_step(s, where, idx) -> dict:
    where = f"{where}.steps[{idx}]"
    if isinstance(s, str):
        s = {"run": s}
    if not isinstance(s, dict):
        raise PipelineError(f"{where} must be a mapping with a run command.")
    _unknown(s, STEP_KEYS, where)
    run = s.get("run")
    if not isinstance(run, str) or not run.strip():
        raise PipelineError(f"{where} needs a non-empty run command.")
    if len(run) > 64 * 1024 or "\0" in run:
        raise PipelineError(f"{where}.run is too long.")
    name = s.get("name")
    if name is not None and not isinstance(name, str):
        raise PipelineError(f"{where}.name must be text.")
    name = (name or run.strip().splitlines()[0])[:120]
    return {"name": name, "run": run, "env": _env(s.get("env"), f"{where}.env"),
            "timeout": _timeout(s.get("timeout"), f"{where}.timeout")}


def parse(text: str | bytes) -> dict:
    """Pipeline YAML → normalized dict (see docs). Raises PipelineError."""
    if isinstance(text, bytes):
        if len(text) > MAX_FILE_BYTES:
            raise PipelineError("The pipeline file is larger than 256 KB.")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            raise PipelineError("The pipeline file is not valid UTF-8.")
    if len(text) > MAX_FILE_BYTES:
        raise PipelineError("The pipeline file is larger than 256 KB.")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(e, "problem", None) or "invalid YAML"
        raise PipelineError(f"Invalid YAML{where}: {problem}.")
    if not isinstance(raw, dict):
        raise PipelineError("The pipeline file must be a mapping with a jobs section.")
    # YAML 1.1 reads a bare `on:` key as the boolean true.
    if True in raw and "on" not in raw:
        raw["on"] = raw.pop(True)
    for k in raw:
        if not isinstance(k, str):
            raise PipelineError(f"Unexpected key {k!r}.")
    _unknown(raw, TOP_KEYS, "pipeline")

    top_image = _image(raw.get("image"), "image")
    top_env = _env(raw.get("env"), "env")
    top_timeout = _timeout(raw.get("timeout"), "timeout")
    jobs_raw = raw.get("jobs")
    if not isinstance(jobs_raw, dict) or not jobs_raw:
        raise PipelineError("jobs must be a mapping with at least one job.")
    if len(jobs_raw) > MAX_JOBS:
        raise PipelineError(f"At most {MAX_JOBS} jobs are allowed.")

    jobs, names = [], [str(n) for n in jobs_raw]
    for name, j in jobs_raw.items():
        name = str(name)
        where = f"jobs.{name}"
        if not JOB_RE.match(name):
            raise PipelineError(f"{where}: job names use letters, digits, dots, dashes and underscores (max 64).")
        if not isinstance(j, dict):
            raise PipelineError(f"{where} must be a mapping with steps.")
        _unknown(j, JOB_KEYS, where)
        steps_raw = j.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise PipelineError(f"{where}.steps must be a list with at least one step.")
        if len(steps_raw) > MAX_STEPS:
            raise PipelineError(f"{where}: at most {MAX_STEPS} steps are allowed.")
        needs = _str_list(j.get("needs"), f"{where}.needs")
        for n in needs:
            if n not in names:
                raise PipelineError(f"{where}.needs: there is no job named {n!r}.")
            if n == name:
                raise PipelineError(f"{where} cannot need itself.")
        secrets = _str_list(j.get("secrets"), f"{where}.secrets")
        for s in secrets:
            if not ENV_RE.match(s):
                raise PipelineError(f"{where}.secrets: {s!r} is not a valid secret name.")
        jobs.append({
            "name": name,
            "title": str(j["name"])[:120] if j.get("name") else name,
            "image": _image(j.get("image"), f"{where}.image") or top_image,
            "env": top_env | _env(j.get("env"), f"{where}.env"),
            "needs": list(dict.fromkeys(needs)),
            "if": _parse_if(j.get("if"), f"{where}.if"),
            "secrets": list(dict.fromkeys(secrets)),
            "steps": [_parse_step(s, where, i) for i, s in enumerate(steps_raw)],
            "artifacts": _str_list(j.get("artifacts"), f"{where}.artifacts"),
            "timeout": _timeout(j.get("timeout"), f"{where}.timeout") or top_timeout,
        })
    _check_cycles(jobs)
    return {"on": _parse_on(raw.get("on")), "jobs": jobs}


def _check_cycles(jobs: list[dict]):
    needs = {j["name"]: j["needs"] for j in jobs}
    state: dict[str, int] = {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            cyc = " -> ".join(path[path.index(n):] + [n])
            raise PipelineError(f"Jobs depend on each other in a circle: {cyc}.")
        state[n] = 1
        for m in needs[n]:
            visit(m, path + [n])
        state[n] = 2

    for n in needs:
        visit(n, [])


def order(jobs: list[dict]) -> list[dict]:
    """Jobs in a runnable order: dependencies first, otherwise as written."""
    done, out, pending = set(), [], list(jobs)
    while pending:
        for j in pending:
            if all(n in done for n in j["needs"]):
                out.append(j)
                done.add(j["name"])
                pending.remove(j)
                break
        else:  # unreachable after _check_cycles
            raise PipelineError("Jobs depend on each other in a circle.")
    return out


# ------------------------------------------------------------- triggering


def push_matches(pipeline: dict, branch: str | None, tag: str | None) -> bool:
    push = pipeline["on"]["push"]
    if not push:
        return False
    if branch is not None:
        return ref_match(push["branches"], branch)
    if tag is not None:
        return ref_match(push["tags"], tag)
    return False


def job_enabled(job: dict, branch: str | None, tag: str | None) -> bool:
    cond = job.get("if")
    if not cond:
        return True
    if branch is not None and "branch" in cond and ref_match(cond["branch"], branch):
        return True
    return tag is not None and "tag" in cond and ref_match(cond["tag"], tag)
