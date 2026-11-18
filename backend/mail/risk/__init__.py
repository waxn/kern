"""Rule-based phishing risk scoring. See rules.py (logic) and rules.yaml
(weights/thresholds)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings

from . import rules as rules_mod
from .rules import RULES, RiskInput

log = logging.getLogger("kern.mail.risk")
LEVELS = ["low", "medium", "high"]


@lru_cache(maxsize=1)
def config() -> dict:
    path = Path(settings.RISK_RULES_FILE)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("thresholds", {"medium": 30, "high": 60})
    data.setdefault("rules", {})
    return data


@lru_cache(maxsize=1)
def brands() -> list[dict]:
    with open(Path(__file__).with_name("brands.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def level_for(score: int) -> str:
    t = config()["thresholds"]
    if score >= t["high"]:
        return "high"
    if score >= t["medium"]:
        return "medium"
    return "low"


def evaluate(x: RiskInput, *, skip_history: bool = False) -> tuple[int, str, list[dict]]:
    findings = []
    cfg = config()["rules"]
    for rule_id, meta in RULES.items():
        rc = cfg.get(rule_id, {})
        if rc.get("enabled", True) is False or rule_id not in cfg:
            continue
        if skip_history and meta["history"]:
            continue
        try:
            reason = meta["fn"](x)
        except Exception:
            log.exception("risk rule %s crashed", rule_id)
            continue
        if reason:
            findings.append({"rule": rule_id, "title": meta["title"], "reason": reason,
                             "weight": int(rc.get("weight", 0))})
    score = max(0, sum(f["weight"] for f in findings))
    return score, level_for(score), findings


def describe_rules() -> dict:
    cfg = config()
    return {
        "thresholds": cfg["thresholds"],
        "rules": [
            {"id": rid, "title": m["title"], "description": m["doc"],
             "weight": cfg["rules"].get(rid, {}).get("weight", 0),
             "enabled": rid in cfg["rules"] and cfg["rules"][rid].get("enabled", True) is not False}
            for rid, m in RULES.items()
        ],
    }


def raise_risk(message, findings: list[dict]) -> None:
    """For later pipeline stages (e.g. a local model): ADD findings. This can
    only ever raise the score/level, never lower it."""
    extra = sum(max(0, int(f.get("weight", 0))) for f in findings)
    if extra <= 0:
        return
    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    message.risk_findings = list(message.risk_findings or []) + findings
    message.risk_score = message.risk_score + extra
    new_level = level_for(message.risk_score)
    if order.get(new_level, 0) > order.get(message.risk_level or "low", 0):
        message.risk_level = new_level
    message.save(update_fields=["risk_findings", "risk_score", "risk_level"])


__all__ = ["evaluate", "describe_rules", "raise_risk", "RiskInput", "rules_mod"]
