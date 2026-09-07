from datetime import datetime, timezone

from stinky_api.developer_history_calibration_readiness import (
    assess_developer_history_calibration_readiness,
)


def _launch(mint, observed_at, outcome="UNKNOWN", ingested_at=None):
    row = {"mint": mint, "observed_at": observed_at, "outcome_status": outcome}
    if ingested_at is not None:
        row["ingested_at"] = ingested_at
    return row


def _snapshot(idx, observed_at, launches, evidence_hash=None, ingested_at=None):
    return {
        "id": idx,
        "evidence_hash": evidence_hash or f"hash-{idx}",
        "observed_at": observed_at,
        "ingested_at": ingested_at or observed_at,
        "evidence": {
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "history_state": "KNOWN_HISTORY" if launches else "NEW-UNKNOWN",
            "launch_history": {
                "historical_launch_count": len(launches),
                "records": launches,
            },
        },
    }


def test_tiny_sample_is_not_ready_even_with_multiple_snapshots():
    launches = [
        _launch("A", "2026-08-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-08-20T00:00:00+00:00", "FADE"),
    ]
    records = [
        _snapshot(1, "2026-08-21T00:00:00+00:00", launches, "h1"),
        _snapshot(2, "2026-08-22T00:00:00+00:00", launches, "h2"),
        _snapshot(3, "2026-08-23T00:00:00+00:00", launches, "h3"),
        _snapshot(4, "2026-08-24T00:00:00+00:00", launches, "h4"),
    ]

    result = assess_developer_history_calibration_readiness(records)

    assert result["ready"] is False
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["metrics"]["distinct_prior_launch_count"] == 2
    assert "INSUFFICIENT_DISTINCT_LAUNCHES" in result["blockers"]


def test_duplicate_snapshots_do_not_create_evidence_diversity():
    launches = [
        _launch("A", "2026-08-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-08-03T00:00:00+00:00", "FADE"),
        _launch("C", "2026-08-05T00:00:00+00:00", "HELD"),
        _launch("D", "2026-08-08T00:00:00+00:00", "RUNNER"),
        _launch("E", "2026-08-10T00:00:00+00:00", "FADE"),
    ]
    records = [
        _snapshot(i, f"2026-08-{10 + i:02d}T00:00:00+00:00", launches, "same-hash")
        for i in range(1, 6)
    ]

    result = assess_developer_history_calibration_readiness(records)

    assert result["ready"] is False
    assert result["status"] == "INSUFFICIENT_EVIDENCE_DIVERSITY"
    assert result["metrics"]["distinct_evidence_hash_count"] == 1
    assert "INSUFFICIENT_EVIDENCE_DIVERSITY" in result["blockers"]


def test_unknown_heavy_history_is_not_ready():
    launches = [
        _launch("A", "2026-08-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-08-03T00:00:00+00:00", "UNKNOWN"),
        _launch("C", "2026-08-05T00:00:00+00:00", "UNKNOWN"),
        _launch("D", "2026-08-08T00:00:00+00:00", "UNKNOWN"),
        _launch("E", "2026-08-10T00:00:00+00:00", "UNKNOWN"),
    ]
    records = [
        _snapshot(1, "2026-08-11T00:00:00+00:00", launches[:3], "h1"),
        _snapshot(2, "2026-08-12T00:00:00+00:00", launches[:4], "h2"),
        _snapshot(3, "2026-08-13T00:00:00+00:00", launches, "h3"),
    ]

    result = assess_developer_history_calibration_readiness(records)

    assert result["ready"] is False
    assert result["status"] == "INSUFFICIENT_OUTCOMES"
    assert result["metrics"]["known_outcome_count"] == 1
    assert result["metrics"]["known_outcome_ratio"] == 0.2
    assert "INSUFFICIENT_KNOWN_OUTCOMES" in result["blockers"]
    assert "INSUFFICIENT_OUTCOME_COVERAGE" in result["blockers"]


def test_narrow_time_window_blocks_readiness():
    launches = [
        _launch("A", "2026-08-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-08-02T00:00:00+00:00", "FADE"),
        _launch("C", "2026-08-03T00:00:00+00:00", "HELD"),
        _launch("D", "2026-08-04T00:00:00+00:00", "RUNNER"),
        _launch("E", "2026-08-05T00:00:00+00:00", "FADE"),
    ]
    records = [
        _snapshot(1, "2026-08-05T12:00:00+00:00", launches[:3], "h1"),
        _snapshot(2, "2026-08-06T12:00:00+00:00", launches[:4], "h2"),
        _snapshot(3, "2026-08-07T12:00:00+00:00", launches, "h3"),
    ]

    result = assess_developer_history_calibration_readiness(records)

    assert result["ready"] is False
    assert result["status"] == "INSUFFICIENT_TIME_SPAN"
    assert result["metrics"]["observation_span_days"] == 4.0
    assert "INSUFFICIENT_TIME_SPAN" in result["blockers"]


def test_sufficient_history_is_ready_for_descriptive_calibration_only():
    launches = [
        _launch("A", "2026-07-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-07-05T00:00:00+00:00", "FADE"),
        _launch("C", "2026-07-09T00:00:00+00:00", "HELD"),
        _launch("D", "2026-07-13T00:00:00+00:00", "RUNNER"),
        _launch("E", "2026-07-17T00:00:00+00:00", "UNKNOWN"),
    ]
    records = [
        _snapshot(1, "2026-07-10T00:00:00+00:00", launches[:3], "h1"),
        _snapshot(2, "2026-07-14T00:00:00+00:00", launches[:4], "h2"),
        _snapshot(3, "2026-07-18T00:00:00+00:00", launches, "h3"),
    ]

    result = assess_developer_history_calibration_readiness(records)

    assert result["status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["metrics"]["distinct_prior_launch_count"] == 5
    assert result["metrics"]["known_outcome_count"] == 4
    assert result["metrics"]["known_outcome_ratio"] == 0.8
    assert result["metrics"]["observation_span_days"] == 16.0
    assert result["metrics"]["distinct_evidence_hash_count"] == 3
    assert result["interpretation"] == "DESCRIPTIVE_READINESS_ONLY"
    assert result["calibration_scope"] == "DEVELOPER_HISTORY_DESCRIPTIVE_ONLY"
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False
    for forbidden in ("risk_score", "quality_score", "probability", "confidence", "expected_return"):
        assert forbidden not in result


def test_as_of_excludes_future_snapshots_and_future_or_timestamp_less_launches():
    cutoff = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    visible_launches = [
        _launch("A", "2026-07-01T00:00:00+00:00", "RUNNER"),
        _launch("B", "2026-07-03T00:00:00+00:00", "FADE"),
    ]
    contaminated = visible_launches + [
        _launch("FUTURE", "2026-07-20T00:00:00+00:00", "RUNNER"),
        {"mint": "NO-TIME", "outcome_status": "RUNNER"},
    ]
    records = [
        _snapshot(1, "2026-07-05T00:00:00+00:00", visible_launches, "h1"),
        _snapshot(2, "2026-07-10T00:00:00+00:00", contaminated, "h2"),
        _snapshot(3, "2026-07-20T00:00:00+00:00", contaminated, "future-hash"),
    ]

    result = assess_developer_history_calibration_readiness(records, as_of=cutoff)

    assert result["ready"] is False
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["metrics"]["visible_snapshot_count"] == 2
    assert result["metrics"]["distinct_prior_launch_count"] == 2
    assert result["metrics"]["distinct_evidence_hash_count"] == 2
    assert result["temporal_integrity"]["excluded_snapshot_count"] == 1
    assert result["temporal_integrity"]["excluded_launch_count"] == 2
    assert result["temporal_integrity"]["missing_or_invalid_timestamps_fail_closed"] is True
    assert result["temporal_cutoff_enforced"] is True


def test_invalid_as_of_fails_closed():
    result = assess_developer_history_calibration_readiness([], as_of="not-a-time")

    assert result["status"] == "UNKNOWN"
    assert result["ready"] is False
    assert result["blockers"] == ["INVALID_AS_OF"]
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
