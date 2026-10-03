"""Regression contracts for API dead-listener recovery and safe Genesis shutdown.

These are source-level tests so CI can verify Windows launcher safety without
starting Docker Desktop or Windows service processes on the runner.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_core_http_supervisors_recycle_sustained_dead_listener():
    t = read("scripts/run_genesis_service.py")
    assert "API_HEALTH_FAILURE_GRACE_SECONDS = 30.0" in t
    assert "API_STARTUP_GRACE_SECONDS = 60.0" in t
    assert "API_HEALTH_RECYCLE_EXIT = 86" in t
    assert "watched_url = healthy_url" in t
    assert 'watched_url = healthy_url if name == "api" else None' not in t
    assert '("event-log", 8002, "http://127.0.0.1:8002/health")' in t
    assert '("api", 8010, "http://127.0.0.1:8010/health")' in t
    assert '("web", 3000, "http://127.0.0.1:3000/operator")' in t
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
    assert "docker.exe" not in chunk.lower()
    assert "docker desktop" not in chunk.lower()
    assert "dockerd" not in chunk.lower()
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


def test_supervisor_failure_state_is_durable_per_service():
    t = read("scripts/run_genesis_service.py")
    assert 'write_state(log_dir / "runtime-state.json", payload)' in t
    assert 'write_state(log_dir / ("runtime-state-" + name + ".json"), payload)' in t
    assert '"service": name' in t
    assert '"supervisor_pid": os.getpid()' in t
    assert '"supervisor_started_at": supervisor_started_at' in t
    assert '"supervisor_phase": phase or "RUNNING"' in t
    assert 'write_supervisor_ownership_state(phase or "RUNNING", services=core)' in t
    assert 'dump_runtime("FAILED")' in t


def test_dependency_watchdog_starts_only_existing_stopped_containers():
    t = read("scripts/run_genesis_service.py")
    assert '[docker, "ps", "-a", "--format", "{{.Names}}|{{.State}}"]' in t
    assert 'if states.get(name) and states[name] != "running"' in t
    assert "if stopped:" in t
    assert 'hidden_run([docker, "start", *stopped], timeout=40)' in t
    assert 'hidden_run([docker, "start", *WATCH_CONTAINERS], timeout=40)' not in t


def test_stopped_watch_container_parser_ignores_running_and_missing_dependencies():
    spec = importlib.util.spec_from_file_location(
        "run_genesis_service_watchdog_test", ROOT / "scripts" / "run_genesis_service.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = "stinky-postgres|running\nstinky-redis|exited\nunrelated|exited\n"
    assert mod.stopped_watch_containers(raw) == ["stinky-redis"]


def test_healthy_core_supervisor_heartbeats_runtime_state():
    t = read("scripts/run_genesis_service.py")
    assert "last_heartbeat = 0.0" in t
    assert "if now - last_heartbeat >= 60:" in t
    assert 'dump_runtime("RUNNING")' in t
    assert "last_heartbeat = now" in t


def test_paper_workers_use_capped_genesis_supervisor():
    runtime = read("scripts/run_genesis_service.py")
    starter = read("scripts/start_paper_runtime.py")
    assert '"paper-intake-producer"' in runtime
    assert '"paper-runtime"' in runtime
    assert 'run_supervised([py, "-m", "stinky_api.prospective_paper_policy_runtime"])' in runtime
    assert 'run_supervised([py, "-m", "stinky_api.paper_runtime_worker"])' in runtime
    assert '[exe, str(supervisor), "--name", name]' in starter
    assert 'subprocess.Popen([exe, "-m", module]' not in starter


def test_non_http_supervisor_heartbeat_proves_supervision_not_application_health():
    t = read("scripts/run_genesis_service.py")
    assert 'dump_runtime("SUPERVISING")' in t
    assert "while proc.poll() is None:" in t
    assert "heartbeat is not an assertion that the application is healthy" in t
    assert 'dump_runtime("RUNNING")' in t


def test_paper_worker_starter_rejects_pid_existence_without_fresh_owned_heartbeat():
    t = read("scripts/start_paper_runtime.py")
    assert "def _owned_supervisor" in t
    assert 'state.get("service") != name' in t
    assert 'state.get("supervisor_pid") != pid' in t
    assert "STATE_MAX_AGE_SECONDS" in t
    assert 'supervisor_phase") or "").upper() == "FAILED"' in t
    assert "if _alive(old):" not in t
    assert "if _owned_supervisor(old, name, logs):" in t


def test_paper_worker_startup_requires_supervisor_proof_and_canonicalizes_pid_file():
    starter = read("scripts/start_paper_runtime.py")
    runtime = read("scripts/run_genesis_service.py")
    assert "STARTUP_PROOF_SECONDS" in starter
    assert "_wait_for_owned_supervisor(proc, name, logs, launch_token)" in starter
    assert 'known[name] = owned_pid' in starter
    assert '"supervisor_launch_token"' in runtime
    assert "STARTUP FAILED: supervisor ownership/heartbeat was not proven" in starter
    assert "_terminate_started_tree(proc)" in starter
    assert "tmp.replace(pid_file)" in starter
    assert 'pid_file.open("a"' not in starter
    assert '"supervisor_pid": os.getpid()' in runtime
    assert '"supervisor_started_at": supervisor_started_at' in runtime
