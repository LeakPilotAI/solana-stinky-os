from datetime import datetime, timezone

from stinky_api.developer_history_calibration_stability import assess_developer_history_calibration_stability


def _launch(i: int, outcome: str, day: int) -> dict:
    return {"mint": f"M{i}", "observed_at": f"2026-08-{day:02d}T00:00:00+00:00", "outcome_status": outcome}


def _records(launches: list[dict]) -> list[dict]:
    evidence = {"history_state": "KNOWN_HISTORY", "launch_history": {"historical_launch_count": len(launches), "records": launches}}
    return [
        {"id": 1, "evidence_hash": "h1", "observed_at": datetime(2026, 8, 25, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 25, tzinfo=timezone.utc), "evidence": evidence},
        {"id": 2, "evidence_hash": "h2", "observed_at": datetime(2026, 8, 26, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 26, tzinfo=timezone.utc), "evidence": evidence},
        {"id": 3, "evidence_hash": "h3", "observed_at": datetime(2026, 8, 27, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 27, tzinfo=timezone.utc), "evidence": evidence},
    ]


def test_stable_early_late_history_passes_descriptive_stability():
    launches = [
        _launch(1, "RUNNER", 1), _launch(2, "FADE", 5), _launch(3, "HELD", 9),
        _launch(4, "RUNNER", 13), _launch(5, "FADE", 17), _launch(6, "HELD", 21),
    ]
    result = assess_developer_history_calibration_stability(_records(launches))
    assert result["readiness_status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["stability_status"] == "STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["stable"] is True
    assert result["slice_sizes"] == {"early": 3, "late": 3}
    assert result["blockers"] == []
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False


def test_outcome_regime_drift_blocks_stability():
    launches = [
        _launch(1, "RUNNER", 1), _launch(2, "RUNNER", 5), _launch(3, "RUNNER", 9),
        _launch(4, "FADE", 13), _launch(5, "FADE", 17), _launch(6, "FADE", 21),
    ]
    result = assess_developer_history_calibration_stability(_records(launches))
    assert result["stable"] is False
    assert result["stability_status"] == "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    assert "OUTCOME_REGIME_DRIFT" in result["blockers"]
    assert result["drift"]["max_outcome_share_drift"] == 1.0


def test_readiness_must_pass_before_stability_is_evaluated():
    launches = [_launch(1, "RUNNER", 1), _launch(2, "FADE", 5), _launch(3, "HELD", 9), _launch(4, "RUNNER", 13)]
    result = assess_developer_history_calibration_stability(_records(launches))
    assert result["stable"] is False
    assert result["stability_status"] == "NOT_EVALUATED"
    assert result["blockers"] == ["READINESS_GATE_NOT_PASSED"]


def test_six_launch_stability_requires_two_known_outcomes_per_slice():
    launches = [
        _launch(1, "RUNNER", 1), _launch(2, "UNKNOWN", 5), _launch(3, "UNKNOWN", 9),
        _launch(4, "RUNNER", 13), _launch(5, "FADE", 17), _launch(6, "HELD", 21),
    ]
    result = assess_developer_history_calibration_stability(_records(launches))
    assert result["readiness_status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["stable"] is False
    assert "INSUFFICIENT_SLICE_OUTCOMES" in result["blockers"]


def test_as_of_excludes_future_launches_before_slicing():
    launches = [
        _launch(1, "RUNNER", 1), _launch(2, "FADE", 5), _launch(3, "HELD", 9),
        _launch(4, "RUNNER", 13), _launch(5, "FADE", 17), _launch(6, "HELD", 21),
        {"mint": "FUTURE", "observed_at": "2026-09-20T00:00:00+00:00", "outcome_status": "RUNNER"},
        {"mint": "NO-TIME", "outcome_status": "RUNNER"},
    ]
    records = _records(launches)
    result = assess_developer_history_calibration_stability(records, as_of="2026-09-01T00:00:00+00:00")
    assert result["slice_sizes"] == {"early": 3, "late": 3}
    assert result["temporal_integrity"]["excluded_launch_count"] == 2
    assert result["temporal_cutoff_enforced"] is True


def test_duplicate_mint_cannot_manufacture_slice_depth():
    launches = [
        _launch(1, "RUNNER", 1), _launch(2, "FADE", 5), _launch(3, "HELD", 9),
        _launch(4, "RUNNER", 13), _launch(5, "FADE", 17),
        {"mint": "M5", "observed_at": "2026-08-18T00:00:00+00:00", "outcome_status": "FADE"},
    ]
    result = assess_developer_history_calibration_stability(_records(launches))
    assert result["stability_status"] == "NOT_EVALUATED"
    assert result["readiness_status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
