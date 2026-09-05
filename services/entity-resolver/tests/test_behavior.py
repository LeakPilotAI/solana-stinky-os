from datetime import datetime, timedelta, timezone

from entity_resolver.behavior import build_behavioral_fingerprint, cadence_bucket


def test_cadence_bucket_boundaries() -> None:
    assert cadence_bucket(None) == "unknown"
    assert cadence_bucket(3600) == "high_frequency"
    assert cadence_bucket(3601) == "active"
    assert cadence_bucket(86400) == "active"
    assert cadence_bucket(86401) == "recurring"
    assert cadence_bucket(604800) == "recurring"
    assert cadence_bucket(604801) == "sparse"


def test_behavioral_fingerprint_is_descriptive_and_preserves_unknown_outcomes() -> None:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    launches = [
        {"observed_at": start, "outcome_status": "completed"},
        {"observed_at": start + timedelta(hours=2), "outcome_status": None},
        {"observed_at": start + timedelta(hours=6), "outcome_status": "completed"},
    ]

    result = build_behavioral_fingerprint(launches)

    assert result["launch_count"] == 3
    assert result["outcomes_known"] == 2
    assert result["completed_count"] == 2
    assert result["outcomes_unknown"] == 1
    assert result["outcome_coverage"] == 2 / 3
    assert result["first_launch_at"] == start.isoformat()
    assert result["last_launch_at"] == (start + timedelta(hours=6)).isoformat()
    assert result["median_launch_interval_sec"] == 10800.0
    assert result["cadence_bucket"] == "active"
    assert result["evidence_basis"] == "entity_launches"


def test_empty_history_is_unknown_not_negative() -> None:
    result = build_behavioral_fingerprint([])

    assert result["launch_count"] == 0
    assert result["outcomes_known"] == 0
    assert result["completed_count"] == 0
    assert result["outcomes_unknown"] == 0
    assert result["outcome_coverage"] is None
    assert result["cadence_bucket"] == "unknown"
