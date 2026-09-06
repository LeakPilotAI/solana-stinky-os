import pytest

from stinky_api.market_pattern_regime_stability import assess_regime_conditioned_stability


def _record(occurrence_id: int, observed_at: str, before: float, after: float):
    return {
        "occurrence_id": occurrence_id,
        "pattern_observed_at": observed_at,
        "baseline_metrics": {"price_usd": before},
        "followup_records": [{"horizon": "1h", "metrics": {"price_usd": after}}],
    }


def _seg(ids, regime):
    return [
        {"occurrence_id": oid, "pattern_observed_at": f"2026-01-{oid:02d}T00:00:00+00:00", "regime_state": regime}
        for oid in ids
    ]


def test_stability_uses_chronological_reference_and_unseen_later_evaluation():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "p1",
        "records": [
            _record(4, "2026-01-04T00:00:00+00:00", 1.0, 1.10),
            _record(1, "2026-01-01T00:00:00+00:00", 1.0, 1.10),
            _record(6, "2026-01-06T00:00:00+00:00", 1.0, 1.12),
            _record(3, "2026-01-03T00:00:00+00:00", 1.0, 1.10),
            _record(5, "2026-01-05T00:00:00+00:00", 1.0, 1.11),
            _record(2, "2026-01-02T00:00:00+00:00", 1.0, 1.10),
        ],
    }
    segmentation = {
        "status": "OBSERVED",
        "records": _seg(range(1, 7), "STABLE_DOMINANT"),
    }

    result = assess_regime_conditioned_stability(
        calibration,
        segmentation,
        min_reference_occurrences=4,
        min_evaluation_occurrences=2,
        max_median_drift_pct_points=5.0,
    )

    stable = result["regimes"]["STABLE_DOMINANT"]
    assert stable["reference_occurrence_ids"] == [1, 2, 3, 4]
    assert stable["evaluation_occurrence_ids"] == [5, 6]
    assert stable["stability_status"] == "STABLE"
    assert stable["evaluation_window_unseen_by_reference"] is True
    assert result["future_evaluation_leakage_permitted"] is False
    assert result["regime_assignment_leakage_permitted"] is False


def test_stability_flags_large_later_drift_as_unstable():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "p1",
        "records": [
            _record(1, "2026-01-01T00:00:00+00:00", 1.0, 1.10),
            _record(2, "2026-01-02T00:00:00+00:00", 1.0, 1.10),
            _record(3, "2026-01-03T00:00:00+00:00", 1.0, 1.10),
            _record(4, "2026-01-04T00:00:00+00:00", 1.0, 1.10),
            _record(5, "2026-01-05T00:00:00+00:00", 1.0, 0.50),
            _record(6, "2026-01-06T00:00:00+00:00", 1.0, 0.50),
        ],
    }
    segmentation = {"status": "OBSERVED", "records": _seg(range(1, 7), "DEGRADING_DOMINANT")}

    result = assess_regime_conditioned_stability(
        calibration,
        segmentation,
        min_reference_occurrences=4,
        min_evaluation_occurrences=2,
        max_median_drift_pct_points=25.0,
    )

    regime = result["regimes"]["DEGRADING_DOMINANT"]
    assert regime["stability_status"] == "UNSTABLE"
    assert regime["median_drift_pct_points"] == pytest.approx(60.0)
    assert "DEGRADING_DOMINANT" in result["unstable_regimes"]


def test_stability_preserves_small_regime_samples_as_insufficient():
    calibration = {
        "status": "OBSERVED",
        "pattern_hash": "p1",
        "records": [
            _record(1, "2026-01-01T00:00:00+00:00", 1.0, 1.10),
            _record(2, "2026-01-02T00:00:00+00:00", 1.0, 1.12),
            _record(3, "2026-01-03T00:00:00+00:00", 1.0, 1.11),
        ],
    }
    segmentation = {"status": "OBSERVED", "records": _seg(range(1, 4), "IMPROVING_DOMINANT")}

    result = assess_regime_conditioned_stability(
        calibration,
        segmentation,
        min_reference_occurrences=3,
        min_evaluation_occurrences=2,
    )

    assert result["regimes"]["IMPROVING_DOMINANT"]["stability_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["stable_regimes"] == []
    assert result["unstable_regimes"] == []
    assert result["missing"] == ["sufficient_regime_conditioned_chronological_evidence"]


def test_stability_has_no_predictive_authority_fields():
    calibration = {"status": "OBSERVED", "pattern_hash": "p1", "records": []}
    segmentation = {"status": "OBSERVED", "records": []}
    result = assess_regime_conditioned_stability(calibration, segmentation)

    forbidden = {"prediction", "probability", "confidence", "risk", "quality", "trade_signal", "expected_return"}
    assert forbidden.isdisjoint(result)
    assert result["evidence_only"] is True
