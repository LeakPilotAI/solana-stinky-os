from stinky_api.market_pattern_rolling_calibration import track_rolling_pattern_calibration


def _record(i, followup):
    return {
        "pattern_observed_at": f"2026-09-{i:02d}T00:00:00Z",
        "baseline_metrics": {"price_usd": 1.0},
        "followup_records": [{"horizon": "1h", "metrics": {"price_usd": followup}}],
    }


def _ready():
    return {"readiness_status": "CALIBRATION_READY"}


def test_rolling_windows_are_strictly_chronological_and_degrade():
    records = [
        _record(1, 1.10), _record(2, 1.10), _record(3, 1.10), _record(4, 1.10),
        _record(5, 1.10), _record(6, 1.10), _record(7, 1.10), _record(8, 1.10),
        _record(9, 1.12), _record(10, 1.12),
        _record(11, 1.50), _record(12, 1.50),
    ]
    calibration = {"status": "OBSERVED", "pattern_hash": "h", "records": records}
    result = track_rolling_pattern_calibration(
        calibration,
        _ready(),
        min_reference_occurrences=8,
        evaluation_window_occurrences=2,
        trend_change_threshold_pct_points=5.0,
    )

    assert result["status"] == "OBSERVED"
    assert result["window_count"] == 2
    assert result["evaluated_window_count"] == 2
    assert result["trend_status"] == "DEGRADING"
    assert result["windows"][0]["reference_occurrence_count"] == 8
    assert result["windows"][0]["evaluation_occurrence_count"] == 2
    assert result["windows"][0]["reference_window"]["last_observed_at"].startswith("2026-09-08")
    assert result["windows"][0]["evaluation_window"]["first_observed_at"].startswith("2026-09-09")
    assert result["windows"][1]["reference_occurrence_count"] == 10
    assert result["windows"][1]["evaluation_window"]["first_observed_at"].startswith("2026-09-11")
    assert result["mean_error_change_first_to_last_pct_points"] > 5.0
    assert result["evidence_only"] is True
    assert all(key not in result for key in ("prediction", "probability", "confidence", "risk", "quality", "trade_signal"))


def test_rolling_trend_can_improve():
    records = [
        _record(1, 1.10), _record(2, 1.10), _record(3, 1.10), _record(4, 1.10),
        _record(5, 1.10), _record(6, 1.10), _record(7, 1.10), _record(8, 1.10),
        _record(9, 1.40), _record(10, 1.40),
        _record(11, 1.15), _record(12, 1.15),
    ]
    calibration = {"status": "OBSERVED", "pattern_hash": "h", "records": records}
    result = track_rolling_pattern_calibration(calibration, _ready(), min_reference_occurrences=8, evaluation_window_occurrences=2)
    assert result["trend_status"] == "IMPROVING"


def test_rolling_trend_stable_with_small_change():
    records = [
        _record(1, 1.10), _record(2, 1.10), _record(3, 1.10), _record(4, 1.10),
        _record(5, 1.10), _record(6, 1.10), _record(7, 1.10), _record(8, 1.10),
        _record(9, 1.12), _record(10, 1.12),
        _record(11, 1.13), _record(12, 1.13),
    ]
    calibration = {"status": "OBSERVED", "pattern_hash": "h", "records": records}
    result = track_rolling_pattern_calibration(calibration, _ready(), min_reference_occurrences=8, evaluation_window_occurrences=2)
    assert result["trend_status"] == "STABLE"


def test_insufficient_when_fewer_than_two_evaluated_windows():
    records = [_record(i, 1.10) for i in range(1, 11)]
    calibration = {"status": "OBSERVED", "pattern_hash": "h", "records": records}
    result = track_rolling_pattern_calibration(calibration, _ready(), min_reference_occurrences=8, evaluation_window_occurrences=2)
    assert result["trend_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["evaluated_window_count"] == 1
    assert result["missing"] == ["multiple_evaluated_windows"]


def test_as_of_is_preserved_and_invalid_dates_are_excluded():
    records = [_record(i, 1.10) for i in range(1, 13)] + [{"pattern_observed_at": "not-a-time"}]
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "h",
        "records": records,
        "as_of": "2026-09-20T00:00:00+00:00",
        "temporal_cutoff_enforced": True,
    }
    result = track_rolling_pattern_calibration(calibration, _ready(), min_reference_occurrences=8, evaluation_window_occurrences=2)
    assert result["as_of"] == "2026-09-20T00:00:00+00:00"
    assert result["temporal_cutoff_enforced"] is True
    assert result["window_count"] == 2


def test_not_ready_history_fails_closed():
    result = track_rolling_pattern_calibration(
        {"status": "OBSERVED", "pattern_hash": "h", "records": []},
        {"readiness_status": "NOT_CALIBRATION_READY"},
    )
    assert result["status"] == "UNKNOWN"
    assert result["trend_status"] == "INSUFFICIENT_EVIDENCE"
