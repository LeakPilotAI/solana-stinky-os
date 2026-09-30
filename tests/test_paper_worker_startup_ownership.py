from datetime import datetime, timedelta, timezone
import json

from scripts import start_paper_runtime as starter


def _state(tmp_path, *, name="paper-runtime", pid=123, phase="SUPERVISING", as_of=None):
    logs = tmp_path
    payload = {
        "service": name,
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

    wrong_service = _state(tmp_path, name="paper-intake-producer", pid=123)
    assert not starter._owned_supervisor(123, "paper-runtime", wrong_service, now=now)


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
