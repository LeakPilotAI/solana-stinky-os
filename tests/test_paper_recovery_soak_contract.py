from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bounded_soak_contract_is_paper_only_and_durable():
    text = (ROOT / "scripts" / "paper_recovery_soak.py").read_text(encoding="utf-8")
    assert "DEFAULT_DURATION_SECONDS = 300" in text
    assert "soak_duration_too_short" in text
    assert "supervisor_identity_changed" in text
    assert '"heartbeats_advanced"' in text
    assert '"candidate_t0_identity_preserved"' in text
    assert '"intake_payload_identity_preserved"' in text
    assert '"existing_runtime_records_preserved"' in text
    assert '"producer_epoch_unchanged"' in text
    assert '"active_policy_provenance_unchanged"' in text
    assert '"duplicates_after_zero"' in text
    assert '"all_supervisors_owned_at_completion"' in text
    assert '"performance_validation": False' in text
    assert '"idle_runtime_recovery_stability"' in text
    assert "AUTHORITY" in text


def test_bounded_soak_launcher_exists():
    text = (ROOT / "Run-Paper-Recovery-Soak.cmd").read_text(encoding="utf-8")
    assert "paper_recovery_soak.py" in text
    assert "paper-recovery-soak-*.json" in text
