from stinky_api.evidence_paper_policy_readiness import derive_threshold_proposal, wilson_interval


def calibrated_distribution(*, outcomes=(30, 20, 10), market_samples=60, up0=0.40, up100=0.20):
    runner, held, fade = outcomes
    total = sum(outcomes)
    return {
        "status": "CALIBRATED_EMPIRICAL",
        "pattern_hash": "pattern-181",
        "future_evidence_used_in_t0_decisions": False,
        "outcome_distribution": {
            "sample_count": total,
            "counts": {"RUNNER": runner, "HELD": held, "FADE": fade},
        },
        "calibrated_horizons": ["1h"],
        "market_cap_change_distributions": {
            "1h": {
                "status": "CALIBRATED_EMPIRICAL",
                "sample_count": market_samples,
                "probabilities": {
                    "DOWN_GT_50": 0.10,
                    "DOWN_0_TO_50": 0.30,
                    "UP_0_TO_100": up0,
                    "UP_GTE_100": up100,
                },
            }
        },
    }


def criteria():
    return dict(min_closed_outcomes=50, min_market_cap_samples=50, min_outcome_classes=3)


def test_insufficient_sample_stays_unknown_instead_of_manufacturing_thresholds():
    result = derive_threshold_proposal(calibrated_distribution(outcomes=(3, 1, 1), market_samples=5), **criteria())
    assert result["status"] == "UNKNOWN"
    assert "sufficient_closed_outcomes" in result["missing"]
    assert "threshold_proposal" not in result
    assert result["automatic_activation"] is False


def test_missing_outcome_diversity_stays_unknown():
    result = derive_threshold_proposal(calibrated_distribution(outcomes=(55, 5, 0)), **criteria())
    assert result["status"] == "UNKNOWN"
    assert "sufficient_outcome_class_diversity" in result["missing"]


def test_unknown_calibration_stays_unknown():
    result = derive_threshold_proposal({"status": "UNKNOWN"}, **criteria())
    assert result["status"] == "UNKNOWN"
    assert "calibrated_empirical_probability_distribution" in result["missing"]


def test_future_t0_evidence_is_rejected():
    payload = calibrated_distribution()
    payload["future_evidence_used_in_t0_decisions"] = True
    result = derive_threshold_proposal(payload, **criteria())
    assert result["status"] == "UNKNOWN"
    assert "temporal_safe_probability_distribution" in result["missing"]


def test_ready_proposal_uses_conservative_wilson_bounds_not_point_estimates():
    result = derive_threshold_proposal(calibrated_distribution(), **criteria())
    assert result["status"] == "READY_FOR_OPERATOR_REVIEW"
    proposal = result["threshold_proposal"]
    points = result["point_estimates"]
    assert proposal["min_runner_probability"] < points["runner_probability"]
    assert proposal["max_fade_probability"] > points["fade_probability"]
    assert proposal["min_nonnegative_market_cap_probability"] < points["nonnegative_market_cap_probability"]
    assert result["requires_operator_supplied_execution_assumptions"] is True
    assert result["requires_explicit_registry_provisioning"] is True
    assert result["automatic_activation"] is False
    assert result["live_execution"] is False
    assert result["trading_authority"] is False


def test_sufficiency_criteria_are_explicit_and_have_no_hidden_defaults():
    result = derive_threshold_proposal(calibrated_distribution(), min_closed_outcomes=0, min_market_cap_samples=50, min_outcome_classes=3)
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["valid_explicit_sufficiency_criteria"]


def test_wilson_interval_is_bounded_and_rejects_invalid_counts():
    low, high = wilson_interval(5, 10)
    assert 0.0 <= low < 0.5 < high <= 1.0
    assert wilson_interval(11, 10) is None
