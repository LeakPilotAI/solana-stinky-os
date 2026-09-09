from stinky_api.calibrated_probability_distributions import build_calibrated_probability_distributions


def _calibration():
    return {
        "status": "OBSERVED",
        "pattern_hash": "pattern-a",
        "as_of": "2026-09-09T12:00:00+00:00",
        "temporal_cutoff_enforced": True,
        "records": [
            {
                "baseline_metrics": {"market_cap_usd": 100_000},
                "followup_records": [
                    {"horizon": "5m", "metrics": {"market_cap_usd": 40_000}},
                    {"horizon": "1h", "metrics": {"market_cap_usd": 250_000}},
                ],
            },
            {
                "baseline_metrics": {"market_cap_usd": 100_000},
                "followup_records": [
                    {"horizon": "5m", "metrics": {"market_cap_usd": 80_000}},
                    {"horizon": "1h", "metrics": {"market_cap_usd": 150_000}},
                ],
            },
            {
                "baseline_metrics": {"market_cap_usd": 100_000},
                "followup_records": [
                    {"horizon": "5m", "metrics": {"market_cap_usd": 130_000}},
                    {"horizon": "1h", "metrics": {"market_cap_usd": 90_000}},
                ],
            },
        ],
    }


def _distribution():
    return {
        "status": "OBSERVED",
        "as_of": "2026-09-09T12:00:00+00:00",
        "temporal_cutoff_enforced": True,
        "sufficient_horizons": ["5m", "1h"],
    }


def _evaluation(**overrides):
    row = {
        "status": "OBSERVED",
        "as_of": "2026-09-09T12:00:00+00:00",
        "temporal_cutoff_enforced": True,
        "evaluation_status": "OUT_OF_SAMPLE_WITHIN_TOLERANCE",
        "within_tolerance_horizons": ["5m", "1h"],
    }
    row.update(overrides)
    return row


def _journal(label, **overrides):
    row = {
        "status": "OBSERVED",
        "decision": {
            "temporal_cutoff_enforced": True,
            "future_evidence_used": False,
        },
        "outcome": {"label": label},
        "outcome_attached_after_decision": True,
        "t0_decision_rewritten_by_outcome": False,
    }
    row.update(overrides)
    return row


def _journals():
    return [
        _journal("RUNNER"),
        _journal("RUNNER"),
        _journal("HELD"),
        _journal("FADE"),
        _journal("FADE"),
    ]


def test_emits_calibrated_empirical_outcome_and_market_cap_probabilities():
    result = build_calibrated_probability_distributions(
        _calibration(), _distribution(), _evaluation(), _journals()
    )

    assert result["status"] == "CALIBRATED_EMPIRICAL"
    assert result["outcome_distribution"]["probabilities"] == {
        "RUNNER": 0.4,
        "HELD": 0.2,
        "FADE": 0.4,
    }
    assert result["outcome_distribution"]["probabilities_sum_to_one"] is True
    assert result["market_cap_change_distributions"]["5m"]["sample_count"] == 3
    assert result["market_cap_change_distributions"]["5m"]["probabilities"] == {
        "DOWN_GT_50": 1 / 3,
        "DOWN_0_TO_50": 1 / 3,
        "UP_0_TO_100": 1 / 3,
        "UP_GTE_100": 0.0,
    }
    assert result["market_cap_change_distributions"]["1h"]["probabilities"] == {
        "DOWN_GT_50": 0.0,
        "DOWN_0_TO_50": 1 / 3,
        "UP_0_TO_100": 1 / 3,
        "UP_GTE_100": 1 / 3,
    }
    assert result["predictive_authority"] is False
    assert result["trading_authority"] is False
    assert result["live_execution"] is False


def test_out_of_sample_deviation_fails_closed():
    result = build_calibrated_probability_distributions(
        _calibration(),
        _distribution(),
        _evaluation(evaluation_status="OUT_OF_SAMPLE_DEVIATION_OBSERVED"),
        _journals(),
    )

    assert result["status"] == "UNKNOWN"
    assert "out_of_sample_calibration_within_tolerance" in result["missing"]


def test_insufficient_horizon_evidence_fails_closed():
    distribution = _distribution()
    distribution["sufficient_horizons"] = []
    result = build_calibrated_probability_distributions(
        _calibration(), distribution, _evaluation(), _journals()
    )

    assert result["status"] == "UNKNOWN"
    assert "calibrated_market_cap_horizon" in result["missing"]


def test_insufficient_closed_counterfactual_outcomes_fails_closed():
    result = build_calibrated_probability_distributions(
        _calibration(), _distribution(), _evaluation(), _journals()[:2]
    )

    assert result["status"] == "UNKNOWN"
    assert "sufficient_closed_counterfactual_outcomes" in result["missing"]


def test_temporally_unsafe_or_open_journal_entries_are_excluded():
    unsafe = _journal("RUNNER")
    unsafe["decision"]["future_evidence_used"] = True
    open_entry = _journal("FADE", status="OPEN", outcome=None, outcome_attached_after_decision=False)
    entries = _journals() + [unsafe, open_entry]

    result = build_calibrated_probability_distributions(
        _calibration(), _distribution(), _evaluation(), entries
    )

    assert result["status"] == "CALIBRATED_EMPIRICAL"
    assert result["outcome_distribution"]["sample_count"] == 5


def test_temporal_cutoff_must_be_explicit_when_as_of_is_present():
    calibration = _calibration()
    calibration["temporal_cutoff_enforced"] = False
    result = build_calibrated_probability_distributions(
        calibration, _distribution(), _evaluation(), _journals()
    )

    assert result["status"] == "UNKNOWN"
    assert "calibration_temporal_cutoff" in result["missing"]


def test_held_is_preserved_as_its_own_probability_class():
    result = build_calibrated_probability_distributions(
        _calibration(), _distribution(), _evaluation(), _journals()
    )

    assert "HELD" in result["outcome_distribution"]["probabilities"]
    assert result["outcome_distribution"]["counts"]["HELD"] == 1
