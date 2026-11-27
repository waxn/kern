"""What an app is doing right now: its processes, the deployment being worked on, the ones waiting, and
whether the AI builder is busy. One answer for the API (GET /api/apps/<slug>/tasks) and the builder's
``list_processes`` tool.

The database parts are read here; the live parts come from the apps service (the API asks it over the control
port, the builder runs inside it) and are handed in: ``live`` is its status entry for the app and
``processes`` the list from :meth:`Supervisor.processes` (``None``: could not be asked).
"""
from __future__ import annotations

from .models import App, BuilderChat


def _iso(d):
    return d.isoformat() if d else None


def build(app: App, live: dict | None = None, processes: list | None = None, worker_up: bool = False) -> dict:
    process = None
    if live and live.get("running") and live.get("pid"):
        process = {"pid": live["pid"], "uptime_s": live.get("uptime", 0), "restarts": live.get("restarts", 0),
                   "cpu": live.get("cpu", 0), "mem_bytes": live.get("rss", 0)}
    active = app.deployments.filter(status__in=("building", "starting")).order_by("-number").first()
    queued = app.deployments.filter(status="queued").order_by("number")[:20]
    chat = BuilderChat.objects.filter(app=app).first()
    builder = None
    if chat and chat.status in ("queued", "running"):
        last = (chat.progress or [None])[-1] if chat.progress else None
        step = ""
        if isinstance(last, dict):
            step = (last.get("verb", "") + (": " + last["detail"] if last.get("detail") else "")).strip()
        builder = {"status": chat.status, "step": step}
    return {
        "state": app.state, "state_detail": app.state_detail, "enabled": app.enabled, "worker_up": worker_up,
        "process": process,
        "processes": processes or [],
        "deploy": {"number": active.number, "status": active.status, "started": _iso(active.started), "subject": active.subject}
        if active else None,
        "queued": [{"number": d.number, "status": d.status, "trigger": d.trigger} for d in queued],
        "builder": builder,
    }
