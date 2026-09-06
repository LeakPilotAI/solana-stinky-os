from stinky_api.phase10_cohort_provenance import (
    AUTHORITY,
    canonical_completion_event_label,
    canonical_token_outcome_label,
)


def test_tracking_completed_without_outcome_is_not_a_label() -> None:
    payload = {"mint": "mint-a", "wallets_touched": 12, "trades_seen": 30, "duration_sec": 1800}
    assert canonical_completion_event_label(payload) == "UNKNOWN"


def test_explicit_completion_outcomes_remain_canonical() -> None:
    assert canonical_completion_event_label({"outcome_status": "runner"}) == "RUNNER"
    assert canonical_completion_event_label({"outcome": "HELD"}) == "HELD"
    assert canonical_completion_event_label({"status": "fade"}) == "FADE"
    assert canonical_completion_event_label({"status": "completed"}) == "UNKNOWN"


def test_legacy_measured_outcomes_are_mapped_only_when_semantically_safe() -> None:
    assert canonical_token_outcome_label("mega_runner") == "RUNNER"
    assert canonical_token_outcome_label("runner") == "RUNNER"
    assert canonical_token_outcome_label("fade") == "FADE"
    assert canonical_token_outcome_label("mid") == "UNKNOWN"
    assert canonical_token_outcome_label("unknown") == "UNKNOWN"


def test_provenance_audit_has_no_authority() -> None:
    assert AUTHORITY["predictive_authority"] is False
    assert AUTHORITY["trade_signal"] is False
    assert AUTHORITY["risk_inferred"] is False
    assert AUTHORITY["quality_inferred"] is False
    assert AUTHORITY["evidence_only"] is True
