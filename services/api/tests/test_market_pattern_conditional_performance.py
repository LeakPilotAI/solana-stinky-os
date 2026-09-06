from stinky_api.market_pattern_conditional_performance import summarize_conditional_pattern_performance


def _record(occurrence_id, before, after):
    return {
        "occurrence_id": occurrence_id,
        "baseline_metrics": {"price_usd": before},
        "followup_records": [
            {"horizon": "1h", "metrics": {"price_usd": after}},
        ],
    }


def test_conditional_summary_groups_followups_by_historically_assigned_regime():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [
            _record(1, 1.0, 2.0),
            _record(2, 1.0, 1.5),
            _record(3, 1.0, 0.5),
            _record(4, 1.0, 0.75),
        ],
        "evidence_only": True,
    }
    segmentation = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [
            {"occurrence_id": 1, "regime_state": "STABLE_DOMINANT"},
            {"occurrence_id": 2, "regime_state": "STABLE_DOMINANT"},
            {"occurrence_id": 3, "regime_state": "DEGRADING_DOMINANT"},
            {"occurrence_id": 4, "regime_state": "DEGRADING_DOMINANT"},
        ],
        "temporal_assignment_rule": "evidence_through+computed_at+ingested_at<=pattern_observed_at",
        "evidence_only": True,
    }

    result = summarize_conditional_pattern_performance(
        calibration,
        segmentation,
        min_occurrences_per_regime=2,
    )

    assert result["status"] == "OBSERVED"
    assert result["future_regime_leakage_permitted"] is False
    assert set(result["sufficient_regimes"]) == {"STABLE_DOMINANT", "DEGRADING_DOMINANT"}
    stable = result["regimes"]["STABLE_DOMINANT"]
    degrading = result["regimes"]["DEGRADING_DOMINANT"]
    assert stable["occurrence_count"] == 2
    assert degrading["occurrence_count"] == 2
    assert stable["horizons"]["1h"]["metrics"]["price_usd"]["sample_count"] == 2
    assert stable["horizons"]["1h"]["metrics"]["price_usd"]["median_pct_change"] == 75.0
    assert degrading["horizons"]["1h"]["metrics"]["price_usd"]["median_pct_change"] == -37.5
    assert all(k not in result for k in ("prediction", "probability", "confidence", "risk", "quality", "trade_signal"))


def test_conditional_summary_preserves_tiny_samples_as_insufficient():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [_record(1, 1.0, 2.0)],
    }
    segmentation = {
        "status": "OBSERVED",
        "records": [{"occurrence_id": 1, "regime_state": "IMPROVING_DOMINANT"}],
        "temporal_assignment_rule": "cutoff-safe",
    }
    result = summarize_conditional_pattern_performance(calibration, segmentation, min_occurrences_per_regime=3)

    assert result["regimes"]["IMPROVING_DOMINANT"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["sufficient_regimes"] == []
    assert result["missing"] == ["sufficient_regime_conditioned_occurrences"]
