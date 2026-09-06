from stinky_api.pattern_temporal_validation import validate_pattern_temporal_stability


def _row(i, outcome, token="developer.history_state=OBSERVED_HISTORY"):
    return {
        "mint": f"M{i}",
        "row_hash": f"row-{i}",
        "launch_observed_at": f"2026-09-{i+1:02d}T00:00:00+00:00",
        "features": {
            "developer_snapshot": {"history_state": "OBSERVED_HISTORY"},
            "correlation_snapshot": {},
            "market_lifecycle": {"observed_horizons": [], "horizons": {}},
        },
        "label": {"outcome": outcome},
    }


def _discovery(dataset_hash="ds"):
    return {
        "patterns": [{
            "pattern_hash": "p1",
            "pattern_key": "developer.history_state=OBSERVED_HISTORY",
            "feature_tokens": ["developer.history_state=OBSERVED_HISTORY"],
            "support_count": 8,
        }],
        "dataset_hash": dataset_hash,
    }


def test_stable_pattern_when_early_late_distributions_are_close():
    outcomes = ["RUNNER", "HELD", "FADE", "FADE", "RUNNER", "HELD", "FADE", "FADE"]
    dataset = {"dataset_hash": "ds", "rows": [_row(i, o) for i, o in enumerate(outcomes)]}
    result = validate_pattern_temporal_stability(
        dataset, _discovery(), min_slice_support=2, min_known_label_coverage=1.0,
        max_outcome_drift_pct_points=10.0, rolling_window_size=4, rolling_step=2,
    )
    pattern = result["patterns"][0]
    assert pattern["stability_status"] == "STABLE"
    assert pattern["outcome_distribution_drift"]["max_drift_pct_points"] == 0.0
    assert pattern["rolling_window_count"] == 3
    assert result["stability_counts"]["STABLE"] == 1
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_unstable_pattern_when_outcome_distribution_drifts():
    outcomes = ["RUNNER", "RUNNER", "RUNNER", "RUNNER", "FADE", "FADE", "FADE", "FADE"]
    dataset = {"dataset_hash": "ds", "rows": [_row(i, o) for i, o in enumerate(outcomes)]}
    result = validate_pattern_temporal_stability(
        dataset, _discovery(), min_slice_support=2, min_known_label_coverage=1.0,
        max_outcome_drift_pct_points=25.0,
    )
    pattern = result["patterns"][0]
    assert pattern["stability_status"] == "UNSTABLE"
    assert pattern["outcome_distribution_drift"]["max_drift_pct_points"] == 100.0
    assert result["stability_counts"]["UNSTABLE"] == 1


def test_unknown_labels_reduce_coverage_and_can_force_insufficient_evidence():
    outcomes = ["RUNNER", "UNKNOWN", "FADE", "UNKNOWN", "RUNNER", "UNKNOWN", "FADE", "UNKNOWN"]
    dataset = {"dataset_hash": "ds", "rows": [_row(i, o) for i, o in enumerate(outcomes)]}
    result = validate_pattern_temporal_stability(
        dataset, _discovery(), min_slice_support=2, min_known_label_coverage=0.75,
    )
    pattern = result["patterns"][0]
    assert pattern["stability_status"] == "INSUFFICIENT_EVIDENCE"
    assert pattern["early"]["known_label_coverage"] == 0.5
    assert pattern["late"]["known_label_coverage"] == 0.5
    assert pattern["early"]["unknown_outcome_count"] == 2


def test_pattern_missing_from_one_half_is_insufficient_not_stable():
    rows = [_row(i, "FADE") for i in range(8)]
    for row in rows[4:]:
        row["features"]["developer_snapshot"]["history_state"] = "NEW-UNKNOWN"
    dataset = {"dataset_hash": "ds", "rows": rows}
    result = validate_pattern_temporal_stability(dataset, _discovery(), min_slice_support=2)
    pattern = result["patterns"][0]
    assert pattern["early"]["support_count"] == 4
    assert pattern["late"]["support_count"] == 0
    assert pattern["stability_status"] == "INSUFFICIENT_EVIDENCE"


def test_empty_input_fails_closed():
    result = validate_pattern_temporal_stability({"dataset_hash": "ds", "rows": []}, {"patterns": []})
    assert result["validation_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["patterns"] == []
    assert result["predictive_authority"] is False
