from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from scripts import start_paper_runtime as starter


def _state(tmp_path, *, name="paper-runtime", state_service=None, pid=123, phase="SUPERVISING", as_of=None):
    logs = tmp_path
    payload = {
        "service": state_service or name,
        "supervisor_pid": pid,
        "supervisor_phase": phase,
        "as_of": as_of or "2026-09-30T07:00:00Z",
    }
    (logs / f"runtime-state-{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    return logs


def test_owned_supervisor_requires_matching_fresh_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(starter, "_alive", lambda pid: True)
    now = datetime(2026, 9, 30, 7, 1, tzinfo=timezone.utc)
    logs = _state(tmp_path)
    assert starter._owned_supervisor(123, "paper-runtime", logs, now=now)

    wrong_pid = _state(tmp_path, pid=456)
    assert not starter._owned_supervisor(123, "paper-runtime", wrong_pid, now=now)

    wrong_service = _state(tmp_path, name="paper-runtime", state_service="paper-intake-producer", pid=123)
    assert not starter._owned_supervisor(123, "paper-runtime", wrong_service, now=now)



def test_windows_supervisor_identity_accepts_service_outside_worker_tuple(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            '"C:\\Python\\python.exe" '
            '"D:\\Work\\Project-Genesis\\scripts\\run_genesis_service.py" '
            '--name "collector"'
        )
        stderr = ""

    monkeypatch.setattr(starter.os, "name", "nt")
    monkeypatch.setattr(
        starter.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    assert "collector" not in starter.WORKERS
    assert starter._windows_supervisor_identity(
        123,
        "collector",
    )


def test_windows_supervisor_identity_rejects_wrong_service_command(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            '"C:\\Python\\python.exe" '
            '"D:\\Work\\Project-Genesis\\scripts\\run_genesis_service.py" '
            '--name "paper-runtime"'
        )
        stderr = ""

    monkeypatch.setattr(starter.os, "name", "nt")
    monkeypatch.setattr(
        starter.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    assert not starter._windows_supervisor_identity(
        123,
        "collector",
    )


def test_windows_supervisor_identity_rejects_empty_service(monkeypatch):
    monkeypatch.setattr(starter.os, "name", "nt")

    assert not starter._windows_supervisor_identity(
        123,
        "",
    )

def test_owned_supervisor_rejects_failed_or_stale_state(monkeypatch, tmp_path):
    monkeypatch.setattr(starter, "_alive", lambda pid: True)
    now = datetime(2026, 9, 30, 7, 10, tzinfo=timezone.utc)
    logs = _state(tmp_path, phase="FAILED", as_of="2026-09-30T07:09:30Z")
    assert not starter._owned_supervisor(123, "paper-runtime", logs, now=now)

    logs = _state(tmp_path, phase="SUPERVISING", as_of="2026-09-30T07:00:00Z")
    assert not starter._owned_supervisor(123, "paper-runtime", logs, now=now)


def test_pid_file_is_rewritten_canonically(tmp_path):
    path = tmp_path / "stinky-pids.txt"
    path.write_text("api=11\npaper-runtime=12\npaper-runtime=13\n", encoding="ascii")
    known = starter._known_pids(path)
    assert known == {"api": 11, "paper-runtime": 13}
    starter._write_pids(path, known)
    assert path.read_text(encoding="ascii") == "api=11\npaper-runtime=13\n"


@pytest.mark.parametrize("child_pid", [123, 456])
def test_startup_returns_actual_heartbeat_pid_bound_to_launch(monkeypatch, tmp_path, child_pid):
    now = datetime.now(timezone.utc).isoformat()
    _state(tmp_path, pid=child_pid, as_of=now)
    path = tmp_path / "runtime-state-paper-runtime.json"
    state = json.loads(path.read_text())
    state["supervisor_launch_token"] = "new-launch"
    path.write_text(json.dumps(state))
    monkeypatch.setattr(starter, "_alive", lambda pid: pid == child_pid)
    proc = SimpleNamespace(pid=123, poll=lambda: None)
    assert starter._wait_for_owned_supervisor(proc, "paper-runtime", tmp_path, "new-launch") == child_pid


@pytest.mark.parametrize("mutation", ["wrong_token", "missing_token", "wrong_service", "dead_child", "failed", "stale", "exited_launcher", "malformed_pid"])
def test_startup_rejects_unbound_or_unhealthy_child(monkeypatch, tmp_path, mutation):
    _state(tmp_path, pid=456, as_of=datetime.now(timezone.utc).isoformat())
    path = tmp_path / "runtime-state-paper-runtime.json"
    state = json.loads(path.read_text())
    state["supervisor_launch_token"] = "new-launch"
    if mutation == "wrong_token":
        state["supervisor_launch_token"] = "old-launch"
    elif mutation == "missing_token":
        state.pop("supervisor_launch_token")
    elif mutation == "wrong_service":
        state["service"] = "paper-intake-producer"
    elif mutation == "failed":
        state["supervisor_phase"] = "FAILED"
    elif mutation == "stale":
        state["as_of"] = "2020-01-01T00:00:00Z"
    elif mutation == "malformed_pid":
        state["supervisor_pid"] = "456"
    path.write_text(json.dumps(state))
    monkeypatch.setattr(starter, "_alive", lambda pid: mutation != "dead_child")
    ticks = iter([0, 0, 99])
    monkeypatch.setattr(starter.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(starter.time, "sleep", lambda _: None)
    proc = SimpleNamespace(pid=123, poll=lambda: 1 if mutation == "exited_launcher" else None)
    assert starter._wait_for_owned_supervisor(proc, "paper-runtime", tmp_path, "new-launch") == 0
