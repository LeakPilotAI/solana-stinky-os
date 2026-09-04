"""Supervisor state machine. No live Windows services."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "genesis_runtime", ROOT / "scripts" / "genesis_runtime.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_restart_cap_trips_failed():
    now = 1_000_000.0
    history = [now - 10] * 8
    ok, phase = mod.should_restart(history, now=now)
    assert ok is False
    assert phase == "FAILED"


def test_restart_allowed_under_cap():
    now = 1_000_000.0
    history = [now - 10, now - 20]
    ok, phase = mod.should_restart(history, now=now)
    assert ok is True
    assert phase == "RESTARTING"


def test_old_restarts_expire():
    now = 1_000_000.0
    history = [now - 10_000] * 20
    ok, phase = mod.should_restart(history, now=now)
    assert ok is True
    assert phase == "RESTARTING"


def test_system_state_running():
    assert mod.system_state({"event-log": "UP", "api": "UP", "web": "UP"}) == "RUNNING"


def test_system_state_degraded():
    assert mod.system_state({"event-log": "UP", "api": "UP", "web": "DOWN"}) == "DEGRADED"


def test_system_state_failed_cores():
    assert mod.system_state({"event-log": "DOWN", "api": "DOWN", "web": "DOWN"}) == "FAILED"


def test_runtime_helper_does_not_hardcode_gate1_threshold():
    t = (ROOT / "packages/stinky-core/src/stinky_core/admission.py").read_text(encoding="utf-8")
    assert "GATE1_VOLUME_5M_USD = 33_000.0" in t
    rt = (ROOT / "scripts/genesis_runtime.py").read_text(encoding="utf-8")
    assert "33_000" not in rt
    assert "33000" not in rt
