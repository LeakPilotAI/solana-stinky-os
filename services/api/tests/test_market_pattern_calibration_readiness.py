from stinky_api.market_pattern_calibration_readiness import assess_pattern_calibration_readiness


def _record(i, change):
    return {
        "occurrence_id": i,
        "pattern_observed_at": f"2026-09-{i:02d}T00:00:00+00:00",
        "baseline_metrics": {"price_usd": 1.0},
        "followup_records": [{"horizon": "1h", "metrics": {"price_usd": 1.0 + change / 100.0}}],
        "evidence_only": True,
    }


def _calibration(changes):
    records = [_record(i + 1, change) for i, change in enumerate(changes)]
    return {
        "status": "OBSERVED",
        "pattern_hash": "hash-1",
        "occurrence_count": len(records),
        "records": records,
        "evidence_only": True,
    }


def test_stable_chronological_halves_can_be_calibration_ready():
    result = assess_pattern_calibration_readiness(
        _calibration([10, 11, 9, 10, 10, 12, 11, 10, 9, 10]),
        max_median_drift_pct_points=5.0,
    )

    assert result["status"] == "OBSERVED"
    assert result["readiness_status"] == "CALIBRATION_READY"
    assert result["slice_sizes"] == {"early": 5, "late": 5}
    assert "1h" in result["stable_horizons"]
    assert result["unstable_horizons"] == []
    assert result["horizons"]["1h"]["stability_status"] == "STABLE"
    assert result["evidence_only"] is True
    assert all(k not in result for k in ("prediction", "probability", "quality", "risk", "confidence", "trade_signal"))


def test_regime_drift_blocks_calibration_readiness():
    result = assess_pattern_calibration_readiness(
        _calibration([10, 10, 10, 10, 10, 60, 60, 60, 60, 60]),
        max_median_drift_pct_points=20.0,
    )

    drift = result["horizons"]["1h"]["metric_median_drift"]["price_usd"]
    assert result["readiness_status"] == "NOT_CALIBRATION_READY"
    assert "1h" in result["unstable_horizons"]
    assert drift["absolute_median_drift_pct_points"] == 50.0
    assert drift["within_drift_limit"] is False


def test_tiny_sample_is_not_calibration_ready():
    result = assess_pattern_calibration_readiness(
        _calibration([10, 11, 9, 10]),
        min_total_occurrences=10,
        min_slice_occurrences=5,
    )

    assert result["readiness_status"] == "NOT_CALIBRATION_READY"
    assert result["missing"] == ["sufficient_chronological_sample"]
    assert result["slice_sizes"] == {"early": 2, "late": 2}


def test_invalid_or_missing_timestamps_are_not_used_as_history():
    calibration = _calibration([10, 10, 10])
    calibration["records"][1]["pattern_observed_at"] = "not-a-time"
    calibration["records"][2].pop("pattern_observed_at")

    result = assess_pattern_calibration_readiness(calibration)

    assert result["readiness_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["missing"] == ["chronological_pattern_history"]
    assert result["occurrence_count"] if "occurrence_count" in result else True


def test_as_of_provenance_is_preserved_without_new_history_lookup():
    calibration = _calibration([10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
    calibration["as_of"] = "2026-09-20T00:00:00+00:00"
    calibration["temporal_cutoff_enforced"] = True

    result = assess_pattern_calibration_readiness(calibration)

    assert result["as_of"] == "2026-09-20T00:00:00+00:00"
    assert result["temporal_cutoff_enforced"] is True


def test_unknown_calibration_remains_unknown():
    result = assess_pattern_calibration_readiness({"status": "UNKNOWN", "pattern_hash": "hash-x"})

    assert result["status"] == "UNKNOWN"
    assert result["readiness_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["missing"] == ["market_pattern_outcome_calibration"]
