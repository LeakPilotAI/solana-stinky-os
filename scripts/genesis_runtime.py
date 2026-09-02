# Pure runtime helpers. No secrets. Gate 1 is not here.
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_RESTARTS = 8
RESTART_WINDOW_SEC = 900.0  # 15 minutes
STATES = ("RUNNING", "DEGRADED", "RESTARTING", "FAILED", "STOPPED")


def should_restart(history: list[float], now: float | None = None) -> tuple[bool, str]:
    """Cap crash loops. history is unix timestamps of recent exits."""
    now = time.time() if now is None else now
    recent = [t for t in history if now - t <= RESTART_WINDOW_SEC]
    if len(recent) >= MAX_RESTARTS:
        return False, "FAILED"
    return True, "RESTARTING"


def record_restart(history: list[float], now: float | None = None) -> list[float]:
    now = time.time() if now is None else now
    recent = [t for t in history if now - t <= RESTART_WINDOW_SEC]
    recent.append(now)
    return recent


def system_state(core: dict[str, str]) -> str:
    """core maps service name -> UP|DOWN|FAILED. HTTP cores: event-log, api, web."""
    vals = list(core.values())
    if not vals:
        return "FAILED"
    if any(v == "FAILED" for v in vals):
        if all(v in ("FAILED", "DOWN") for v in vals):
            return "FAILED"
        return "DEGRADED"
    downs = [k for k, v in core.items() if v != "UP"]
    if not downs:
        return "RUNNING"
    if "api" in downs and "event-log" in downs:
        return "FAILED"
    return "DEGRADED"


def write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
