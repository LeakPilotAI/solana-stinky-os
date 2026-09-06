from stinky_api.market_pattern_calibration_evaluation import evaluate_pattern_calibration_out_of_sample


def _record(i, price_change):
    baseline = 1.0
    return {
        "occurrence_id": i,
        "pattern_observed_at": f"2026-09-{i:02d}T00:00:00+00:00",
        "baseline_metrics": {"price_usd": baseline},
        "followup_records": [{
            "horizon": "1h",
            "metrics": {"price_usd": baseline * (1.0 + price_change / 100.0)},
        }],
        "evidence_only": True,
    }


def test_reference_and_evaluation_windows_are_strictly_chronological():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "hash-1",
        "records": [_record(i, 10.0) for i in range(1, 13)],
        "evidence_only": True,
    }
    readiness = {"readiness_status": "CALIBRATION_READY"}

    result = evaluate_pattern_calibration_out_of_sample(calibration, readiness)

    assert result["status"] == "OBSERVED"
    assert result["reference_occurrence_count"] == 9
    assert result["evaluation_occurrence_count"] == 3
    assert result["reference_window"]["last_observed_at"] < result["evaluation_window"]["first_observed_at"]
    assert result["evaluation_status"] == "OUT_OF_SAMPLE_WITHIN_TOLERANCE"
    metric = result["horizons"]["1h"]["metrics"]["price_usd"]
    assert round(metric["reference_median_pct_change"], 8) == 10.0
    assert round(metric["evaluation_median_pct_change"], 8) == 10.0
    assert metric["within_tolerance"] is True


def test_later_evaluation_deviation_is_observed_without_changing_reference():
    records = [_record(i, 10.0) for i in range(1, 10)] + [_record(i, 80.0) for i in range(10, 13)]
    result = evaluate_pattern_calibration_out_of_sample(
        {"status": "OBSERVED", "pattern_hash": "hash-2", "records": records},
        {"readiness_status": "CALIBRATION_READY"},
    )

    metric = result["horizons"]["1h"]["metrics"]["price_usd"]
    assert round(metric["reference_median_pct_change"], 8) == 10.0
    assert round(metric["evaluation_median_pct_change"], 8) == 80.0
    assert round(metric["absolute_median_error_pct_points"], 8) == 70.0
    assert result["evaluation_status"] == "OUT_OF_SAMPLE_DEVIATION_OBSERVED"
    assert "1h" in result["outside_tolerance_horizons"]


def test_not_ready_patterns_do_not_enter_evaluation():
    result = evaluate_pattern_calibration_out_of_sample(
        {"status": "OBSERVED", "pattern_hash": "hash-3", "records": [_record(1, 10.0)]},
        {"readiness_status": "NOT_CALIBRATION_READY"},
    )

    assert result["status"] == "UNKNOWN"
    assert result["evaluation_status"] == "NOT_EVALUATION_READY"
    assert result["missing"] == ["calibration_ready_history"]


def test_tiny_split_is_blocked_and_as_of_provenance_is_preserved():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "hash-4",
        "records": [_record(i, 10.0) for i in range(1, 7)],
        "as_of": "2026-09-10T00:00:00+00:00",
        "temporal_cutoff_enforced": True,
    }
    result = evaluate_pattern_calibration_out_of_sample(
        calibration,
        {"readiness_status": "CALIBRATION_READY"},
    )

    assert result["evaluation_status"] == "NOT_EVALUATION_READY"
    assert result["missing"] == ["sufficient_out_of_sample_split"]
    assert result["as_of"] == calibration["as_of"]
    assert result["temporal_cutoff_enforced"] is True


def test_evaluation_contract_has_no_trading_or_confidence_fields():
    result = evaluate_pattern_calibration_out_of_sample(
        {"status": "OBSERVED", "pattern_hash": "hash-5", "records": [_record(i, 10.0) for i in range(1, 13)]},
        {"readiness_status": "CALIBRATION_READY"},
    )

    assert result["evidence_only"] is True
    assert all(key not in result for key in ("prediction", "probability", "confidence", "quality", "risk", "trade_signal"))
