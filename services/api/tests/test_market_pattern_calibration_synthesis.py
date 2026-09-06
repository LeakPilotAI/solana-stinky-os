from stinky_api.market_pattern_calibration_synthesis import synthesize_market_pattern_calibration_evidence


def _observed(**extra):
    return {"status": "OBSERVED", "missing": [], "evidence_only": True, **extra}


def test_synthesis_compacts_complete_chain_without_predictive_authority():
    result = synthesize_market_pattern_calibration_evidence(
        rolling=_observed(pattern_hash="p1", trend_status="STABLE"),
        memory=_observed(pattern_hash="p1", records=[{"id": 1}]),
        transitions=_observed(
            pattern_hash="p1",
            current_state="DEGRADING",
            transition_count=3,
            open_degradation_episode=True,
        ),
        regime_memory=_observed(
            pattern_count=6,
            state_counts={"STABLE": 2, "IMPROVING": 1, "DEGRADING": 3, "INSUFFICIENT_EVIDENCE": 0},
        ),
        segmentation=_observed(
            pattern_hash="p1",
            segmented_occurrence_count=5,
            regime_counts={"STABLE_DOMINANT": 3, "DEGRADING_DOMINANT": 2},
        ),
        conditional_performance=_observed(pattern_hash="p1", sufficient_regimes=["STABLE_DOMINANT"]),
        stability=_observed(
            pattern_hash="p1",
            stable_regimes=["STABLE_DOMINANT"],
            unstable_regimes=["DEGRADING_DOMINANT"],
            insufficient_regimes=["MIXED"],
        ),
    )

    assert result["status"] == "OBSERVED"
    assert result["evidence_status"] == "COMPLETE_OBSERVED_CHAIN"
    assert result["current_calibration_state"] == "DEGRADING"
    assert result["transition_count"] == 3
    assert result["open_degradation_episode"] is True
    assert result["regime_memory"]["pattern_count"] == 6
    assert result["conditional_evidence"]["sufficient_regime_count"] == 1
    assert result["chronological_generalization"]["stable_regimes"] == ["STABLE_DOMINANT"]
    assert result["chronological_generalization"]["unstable_regimes"] == ["DEGRADING_DOMINANT"]
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["shared_cause_inferred"] is False
    assert result["interpretation"] == "DESCRIPTIVE_EVIDENCE_ONLY"
    forbidden = {"score", "probability", "confidence", "expected_return", "risk", "quality"}
    assert forbidden.isdisjoint(result)


def test_synthesis_preserves_partial_and_missing_evidence():
    result = synthesize_market_pattern_calibration_evidence(
        rolling={"status": "UNKNOWN", "missing": ["rolling_history"]},
        memory=_observed(pattern_hash="p1", records=[{"id": 1}]),
        transitions={"status": "UNKNOWN", "missing": ["valid_calibration_snapshot_states"]},
        regime_memory=_observed(pattern_count=1, state_counts={"STABLE": 1}),
        segmentation={"status": "UNKNOWN", "missing": ["historical_regime_evidence"]},
        conditional_performance={"status": "UNKNOWN", "missing": ["market_pattern_regime_segmentation"]},
        stability={"status": "UNKNOWN", "missing": ["market_pattern_regime_segmentation"]},
    )

    assert result["status"] == "OBSERVED"
    assert result["evidence_status"] == "PARTIAL_EVIDENCE"
    assert result["chain_status"]["rolling"] == "OBSERVED"
    assert "rolling_history" in result["missing"]
    assert "historical_regime_evidence" in result["missing"]
    assert result["current_calibration_state"] == "INSUFFICIENT_EVIDENCE"


def test_synthesis_keeps_all_unknown_as_unknown():
    unknown = {"status": "UNKNOWN", "missing": ["missing"], "evidence_only": True}
    result = synthesize_market_pattern_calibration_evidence(
        rolling=unknown,
        memory=unknown,
        transitions=unknown,
        regime_memory=unknown,
        segmentation=unknown,
        conditional_performance=unknown,
        stability=unknown,
    )

    assert result["status"] == "UNKNOWN"
    assert result["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["observed_layer_count"] == 0
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
