import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import paper_recovery_drill as drill


@pytest.fixture
def recorded_worker(tmp_path, monkeypatch):
    name, pid = "paper-runtime", 32248
    started = datetime(2026, 9, 30, 12, 35, 52, tzinfo=timezone.utc)
    state = {"service": name, "supervisor_pid": pid,
             "supervisor_started_at": started.isoformat()}
    path = tmp_path / f"runtime-state-{name}.json"
    path.write_text(json.dumps(state))
    (tmp_path / f"{name}.log").write_text(f"[2026-09-30T12:35:52Z] start pid={pid}\n")
    pid_file = tmp_path / "stinky-pids.txt"
    pid_file.write_text(f"{name}={pid}\nother-service=777\n")
    monkeypatch.setattr(drill, "LOGS", tmp_path)
    monkeypatch.setattr(drill, "PID_FILE", pid_file)
    monkeypatch.setattr(drill, "_alive", lambda value: value == pid)
    monkeypatch.setattr(drill, "_windows_process_started_at", lambda value: started + timedelta(seconds=320))
    return name, pid, started, path, pid_file


def test_reused_pid_is_unlinked_without_killing_successor_or_deleting_evidence(recorded_worker, monkeypatch):
    name, pid, _, path, pid_file = recorded_worker
    original = path.read_bytes()
    monkeypatch.setattr(drill, "_owned_supervisor", lambda *args: pytest.fail("reused PID cannot be owned"))
    monkeypatch.setattr(drill, "_cleanup_proven_orphan", lambda *args: pytest.fail("must not kill successor"))
    assert drill._reconcile_pid_file() == {"other-service": 777}
    assert path.read_bytes() == original
    assert pid_file.read_text() == "other-service=777\n"
    assert drill._reconcile_pid_file() == {"other-service": 777}


@pytest.mark.parametrize("offset", [None, -320, 0, 5])
def test_missing_or_matching_creation_time_never_proves_reuse(recorded_worker, monkeypatch, offset):
    name, pid, started, _, _ = recorded_worker
    monkeypatch.setattr(drill, "_windows_process_started_at", lambda value: None if offset is None else started + timedelta(seconds=offset))
    assert not drill._proven_reused_pid(name, pid)


@pytest.mark.parametrize("field,value", [("service", "other"), ("supervisor_pid", 99), ("supervisor_started_at", "invalid")])
def test_mismatched_record_does_not_authorize_unlink(recorded_worker, field, value):
    name, pid, _, path, _ = recorded_worker
    state = json.loads(path.read_text())
    state[field] = value
    path.write_text(json.dumps(state))
    assert not drill._proven_reused_pid(name, pid)


def test_unproven_live_pid_still_blocks_and_preserves_metadata(recorded_worker, monkeypatch):
    name, pid, _, path, pid_file = recorded_worker
    (drill.LOGS / f"{name}.log").write_text("unrelated start record\n")
    before = pid_file.read_bytes(), path.read_bytes()
    monkeypatch.setattr(drill, "_owned_supervisor", lambda *args: False)
    monkeypatch.setattr(drill, "_windows_supervisor_identity", lambda *args: False)
    monkeypatch.setattr(drill, "_legacy_supervisor_instance_identity", lambda *args: False)
    monkeypatch.setattr(drill.subprocess, "run", lambda *args, **kwargs: pytest.fail("no process termination"))
    with pytest.raises(RuntimeError, match="live_unowned_supervisor_identity_not_proven"):
        drill._reconcile_pid_file()
    assert (pid_file.read_bytes(), path.read_bytes()) == before
