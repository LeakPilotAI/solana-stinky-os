from pathlib import Path

from scripts.paper_recovery_drill import (
    _duplicates_zero,
    _preserved_subset,
)

ROOT = Path(__file__).resolve().parents[1]


def test_preserved_subset_allows_new_rows_but_rejects_changed_existing_identity():
    before = [{"candidate_id": "c1", "t0_evidence_sha256": "a" * 64}]
    after = [
        {"candidate_id": "c1", "t0_evidence_sha256": "a" * 64},
        {"candidate_id": "c2", "t0_evidence_sha256": "b" * 64},
    ]
    ok, changed = _preserved_subset(before, after, key="candidate_id")
    assert ok is True and changed == []

    altered = [{"candidate_id": "c1", "t0_evidence_sha256": "c" * 64}]
    ok, changed = _preserved_subset(before, altered, key="candidate_id")
    assert ok is False and changed == ["c1"]


def test_duplicate_check_requires_every_identity_count_to_be_zero():
    assert _duplicates_zero({"candidate_source_event_id": 0, "runtime_intake_id": 0})
    assert not _duplicates_zero({"candidate_source_event_id": 1, "runtime_intake_id": 0})


def test_recovery_drill_kills_only_after_genesis_ownership_proof():
    src = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8")
    block = src.split("def _kill_owned_supervisor", 1)[1].split("SNAPSHOT_SQL", 1)[0]
    assert "_owned_detail(name, pid)" in block
    assert '["taskkill", "/PID", str(pid), "/T", "/F"]' in block
    assert "source_container_not_running" not in block


def test_recovery_drill_proves_required_durable_invariants():
    src = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8")
    for token in (
        "candidate_t0_identity_preserved",
        "intake_payload_identity_preserved",
        "existing_runtime_records_preserved",
        "producer_epoch_unchanged",
        "active_policy_provenance_unchanged",
        "duplicates_after_zero",
        "all_supervisors_recovered",
        "both_supervisors_forced_and_restarted",
    ):
        assert token in src
    for table in (
        "paper_prospective_candidate",
        "paper_runtime_intake",
        "paper_runtime_record",
        "paper_intake_producer_state",
        "paper_policy_active",
        "paper_policy_registry",
    ):
        assert table in src


def test_recovery_drill_remains_paper_only_and_has_no_execution_authority():
    src = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8").lower()
    assert '"paper_only": true' in src
    assert '"live_execution": false' in src
    assert '"trading_authority": false' in src
    for forbidden in ("send_transaction", "sign_transaction", "private_key"):
        assert forbidden not in src


def test_recovery_launcher_is_one_command():
    launcher = (ROOT / "Run-Paper-Recovery-Drill.cmd").read_text(encoding="utf-8")
    assert "scripts\\paper_recovery_drill.py" in launcher
    assert "paper-worker recovery drill PASSED" in launcher


def test_paper_supervisor_ownership_heartbeat_is_immediate_and_health_independent():
    src = (ROOT / "scripts" / "run_genesis_service.py").read_text(encoding="utf-8")
    helper = src.split("def write_supervisor_ownership_state", 1)[1].split("def http_ok", 1)[0]
    assert "http_ok(" not in helper
    assert '"supervisor_pid": os.getpid()' in helper
    assert '"supervisor_started_at": supervisor_started_at' in helper
    assert '"supervisor_phase": phase or "RUNNING"' in helper

    initial = src.index('write_supervisor_ownership_state("SUPERVISING")')
    first_core_probe = src.index("url_now = core_url(name)")
    assert initial < first_core_probe


def test_paper_starter_surfaces_log_and_state_when_ownership_proof_fails():
    src = (ROOT / "scripts" / "start_paper_runtime.py").read_text(encoding="utf-8")
    assert "def _tail_service_log" in src
    assert "recent log tail:" in src
    assert "runtime state:" in src
    assert "_terminate_started_tree(proc)" in src


def test_windows_supervisor_liveness_uses_native_api_not_tasklist():
    src = (ROOT / "scripts" / "start_paper_runtime.py").read_text(encoding="utf-8")
    alive = src.split("def _alive", 1)[1].split("def _known_pids", 1)[0]
    assert 'ctypes.WinDLL("kernel32"' in alive
    assert "OpenProcess" in alive
    assert "GetExitCodeProcess" in alive
    assert "STILL_ACTIVE = 259" in alive
    assert 'subprocess.run(["tasklist"' not in alive


def test_stale_live_supervisor_requires_exact_windows_process_identity_before_cleanup():
    starter = (ROOT / "scripts" / "start_paper_runtime.py").read_text(encoding="utf-8")
    identity = starter.split("def _windows_supervisor_identity", 1)[1].split("def _known_pids", 1)[0]
    assert "Get-CimInstance Win32_Process" in identity
    assert "run_genesis_service.py" in identity
    assert '"--name"' in identity
    assert "name.lower()" in identity

    drill = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8")
    cleanup = drill.split("def _cleanup_proven_orphan", 1)[1].split("def _reconcile_pid_file", 1)[0]
    assert "_windows_supervisor_identity(pid, name)" in cleanup
    assert '["taskkill", "/PID", str(pid), "/T", "/F"]' in cleanup
    assert cleanup.index("_windows_supervisor_identity(pid, name)") < cleanup.index('["taskkill"')


def test_reconcile_removes_stale_state_only_after_proven_orphan_cleanup():
    drill = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8")
    reconcile = drill.split("def _reconcile_pid_file", 1)[1].split("def _start_workers", 1)[0]
    assert "_cleanup_proven_orphan(name, pid)" in reconcile
    assert "state_path.unlink()" in reconcile
    assert reconcile.index("_cleanup_proven_orphan(name, pid)") < reconcile.index("state_path.unlink()")


def test_legacy_orphan_identity_binds_pid_state_log_and_native_creation_time():
    src = (ROOT / "scripts" / "start_paper_runtime.py").read_text(encoding="utf-8")
    native = src.split("def _windows_process_started_at", 1)[1].split("def _legacy_supervisor_instance_identity", 1)[0]
    assert "GetProcessTimes" in native
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in native

    legacy = src.split("def _legacy_supervisor_instance_identity", 1)[1].split("def _windows_supervisor_identity", 1)[0]
    assert 'state.get("service") != name' in legacy
    assert 'state.get("supervisor_pid")' in legacy
    assert 'state.get("supervisor_started_at")' in legacy
    assert "_windows_process_started_at(pid)" in legacy
    assert "total_seconds()) > 5.0" in legacy
    assert 'f"[{stamp}] start pid={int(pid)}"' in legacy


def test_orphan_cleanup_accepts_only_command_identity_or_legacy_process_instance_proof():
    src = (ROOT / "scripts" / "paper_recovery_drill.py").read_text(encoding="utf-8")
    cleanup = src.split("def _cleanup_proven_orphan", 1)[1].split("def _reconcile_pid_file", 1)[0]
    assert "command_identity = _windows_supervisor_identity(pid, name)" in cleanup
    assert "legacy_instance_identity = _legacy_supervisor_instance_identity(pid, name, LOGS)" in cleanup
    assert "if not (command_identity or legacy_instance_identity)" in cleanup
    assert cleanup.index("if not (command_identity or legacy_instance_identity)") < cleanup.index('["taskkill"')
