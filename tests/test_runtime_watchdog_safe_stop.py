"""Regression contracts for API dead-listener recovery and safe Genesis shutdown.

These are source-level tests so CI can verify Windows launcher safety without
starting Docker Desktop or Windows service processes on the runner.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_api_supervisor_recycles_sustained_dead_listener():
    t = read("scripts/run_genesis_service.py")
    assert "API_HEALTH_FAILURE_GRACE_SECONDS = 30.0" in t
    assert "API_STARTUP_GRACE_SECONDS = 60.0" in t
    assert "API_HEALTH_RECYCLE_EXIT = 86" in t
    assert 'watched_url = healthy_url if name == "api" else None' in t
    assert "seen_healthy" in t
    assert "unhealthy_since" in t
    assert "terminate_owned_child(proc, reason)" in t
    assert "record_restart(history)" in t
    assert "should_restart(history)" in t
    assert "FAILED after" in t


def test_api_child_kill_is_scoped_and_never_targets_docker():
    t = read("scripts/run_genesis_service.py")
    chunk = t[t.index("def terminate_owned_child") : t.index("def run(")]
    assert '["taskkill", "/PID", str(proc.pid), "/T"]' in chunk
    assert '["taskkill", "/PID", str(proc.pid), "/T", "/F"]' in chunk
    assert "docker" not in chunk.lower()
    assert "/IM" not in chunk


def test_stop_removes_only_genesis_compose_and_keeps_volumes():
    t = read("stop-stinky.ps1")
    assert "compose -p project-genesis" in t
    assert "down --remove-orphans" in t
    assert "compose -p atlas" not in t
    assert "docker system prune" not in t.lower()
    assert "docker rm" not in t.lower()
    assert "Docker Desktop remains running" in t
    assert "ATLAS was not targeted" in t

    # No volume deletion: tomorrow's Genesis start must reuse persistent data.
    compose_line = next(line for line in t.splitlines() if "down --remove-orphans" in line)
    assert " -v" not in compose_line
    assert "--volumes" not in compose_line


def test_stop_never_kills_docker_daemon_and_stops_supervisors_first():
    t = read("stop-stinky.ps1")
    assert 'if ($p -and $p.Name -match "(?i)docker|Docker Desktop|com\\.docker|dockerd")' in t
    assert "run_genesis_service\\.py" in t
    assert "maintain" in t
    compose_at = t.index("down --remove-orphans")
    process_at = t.index("Get-CimInstance Win32_Process")
    assert process_at < compose_at
