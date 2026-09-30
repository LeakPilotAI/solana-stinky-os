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
