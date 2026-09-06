from stinky_api.market_pattern_outcome_distribution import summarize_pattern_outcome_distribution


def _occurrence(occurrence_id, baseline, horizon, followup):
    return {
        "occurrence_id": occurrence_id,
        "mint": f"M{occurrence_id}",
        "baseline_metrics": {"price_usd": baseline, "liquidity_usd": baseline * 100},
        "followup_records": [{
            "horizon": horizon,
            "metrics": {"price_usd": followup, "liquidity_usd": followup * 100},
        }],
        "evidence_only": True,
    }


def test_distribution_summarizes_factual_percent_changes_and_sufficiency():
    records = [
        _occurrence(1, 1.0, "1h", 1.10),
        _occurrence(2, 1.0, "1h", 1.20),
        _occurrence(3, 1.0, "1h", 1.30),
        _occurrence(4, 1.0, "1h", 0.90),
        _occurrence(5, 1.0, "1h", 1.00),
    ]
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "hash-1",
        "occurrence_count": 5,
        "horizon_coverage": {"1h": {"coverage": 1.0}},
        "records": records,
        "evidence_only": True,
    }

    result = summarize_pattern_outcome_distribution(calibration)

    assert result["status"] == "OBSERVED"
    assert result["horizons"]["1h"]["evidence_status"] == "SUFFICIENT_EVIDENCE"
    price = result["horizons"]["1h"]["metric_percent_changes"]["price_usd"]
    assert price["sample_count"] == 5
    assert round(price["median"], 8) == 10.0
    assert round(price["min"], 8) == -10.0
    assert round(price["max"], 8) == 30.0
    assert price["iqr"] is not None
    assert result["evidence_only"] is True
    assert all(key not in result for key in ("prediction", "probability", "quality", "risk", "trade_signal"))


def test_insufficient_when_sample_or_coverage_is_too_small():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "hash-2",
        "occurrence_count": 10,
        "horizon_coverage": {"1h": {"coverage": 0.2}},
        "records": [_occurrence(1, 1.0, "1h", 1.5), _occurrence(2, 1.0, "1h", 1.6)],
        "evidence_only": True,
    }

    result = summarize_pattern_outcome_distribution(calibration)

    assert result["horizons"]["1h"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert "1h" in result["insufficient_horizons"]
    assert result["horizons"]["1h"]["max_metric_sample_count"] == 2


def test_missing_baseline_does_not_become_zero_change():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "hash-3",
        "occurrence_count": 1,
        "horizon_coverage": {"30m": {"coverage": 1.0}},
        "records": [{
            "occurrence_id": 1,
            "baseline_metrics": {},
            "followup_records": [{"horizon": "30m", "metrics": {"price_usd": 2.0}}],
        }],
    }

    result = summarize_pattern_outcome_distribution(calibration, min_sample_count=1)

    assert result["horizons"]["30m"]["metric_percent_changes"] == {}
    assert result["horizons"]["30m"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["horizons"]["30m"]["missing"] == ["baseline_or_followup_metric_evidence"]


def test_unknown_calibration_remains_unknown():
    result = summarize_pattern_outcome_distribution({"status": "UNKNOWN", "pattern_hash": "hash-4"})

    assert result["status"] == "UNKNOWN"
    assert result["horizons"] == {}
    assert result["missing"] == ["market_pattern_outcome_calibration"]
