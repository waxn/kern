"""Starter apps (kernapps/starters/<key>/): the files a new app begins with, plus meta.json for the picker."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "starters"


def all_starters() -> list[dict]:
    out = []
    for d in sorted(ROOT.iterdir()):
        meta = d / "meta.json"
        if d.is_dir() and meta.is_file():
            m = json.loads(meta.read_text())
            out.append({"key": d.name, "name": m["name"], "icon": m.get("icon", ""), "description": m.get("description", ""),
                        "public_paths": m.get("public_paths", []), "order": m.get("order", 99)})
    return sorted(out, key=lambda s: s["order"])


def get(key: str) -> dict | None:
    return next((s for s in all_starters() if s["key"] == key), None)


def files(key: str) -> dict[str, bytes]:
    base = ROOT / key
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != "meta.json" and "__pycache__" not in p.parts:
            out[p.relative_to(base).as_posix()] = p.read_bytes()
    return out
