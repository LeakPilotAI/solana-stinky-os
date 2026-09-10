from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_strict_gate_verifies_legacy_bootstrap_instead_of_replaying_it():
    src = (ROOT / "scripts/strict_startup_schema_gate.py").read_text(encoding="utf-8")
    assert "LEGACY_BOOTSTRAP_MIGRATIONS" in src
    assert "services/event-log/migrations/001_initial_schema.sql" in src
    assert '"events"' in src
    assert "should_skip_legacy_bootstrap" in src
    assert "legacy bootstrap schema is partially initialized" in src
    assert "schema bootstrap already present; verified and skipped" in src


def test_partial_legacy_schema_fails_closed_instead_of_destructive_replay():
    src = (ROOT / "scripts/strict_startup_schema_gate.py").read_text(encoding="utf-8")
    assert "if not present:" in src
    assert "return False" in src
    assert "if missing:" in src
    assert "refusing destructive replay" in src


def test_required_executor_and_paper_tables_remain_strictly_verified():
    from scripts import strict_startup_schema_gate as gate

    assert set(gate.REQUIRED_EXECUTOR_TABLES) == {
        "executor_submission_state",
        "executor_submission_transition_audit",
    }
    assert set(gate.REQUIRED_PAPER_RUNTIME_TABLES) == {
        "paper_runtime_intake",
        "paper_runtime_record",
        "paper_intake_producer_state",
        "paper_prospective_candidate",
    }


def test_startup_gate_still_has_no_live_execution_side_effects():
    src = (ROOT / "scripts/strict_startup_schema_gate.py").read_text(encoding="utf-8").lower()
    for forbidden in ("send_transaction", "sign_transaction", "private_key", "order_submitted=true"):
        assert forbidden not in src
