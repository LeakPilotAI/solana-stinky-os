from stinky_api.historical_outcome_calibration import calibrate_historical_outcomes


def test_calibration_counts_known_unknown_and_completed_outcomes():
    result = calibrate_historical_outcomes(
        {
            "status": "OBSERVED",
            "records": [
                {
                    "entity_id": "a",
                    "launches": [
                        {"outcome_observed": True, "outcome_status": "completed"},
                        {"outcome_observed": True, "outcome_status": "partial"},
                        {"outcome_observed": False, "outcome_status": None},
                    ],
                },
                {"entity_id": "b", "launches": []},
            ],
            "bounded": {"limit_per_entity": 20},
            "evidence_only": True,
        }
    )

    assert result["status"] == "OBSERVED"
    assert result["analogue_count"] == 2
    assert result["analogue_with_launches"] == 1
    assert result["launch_count_observed"] == 3
    assert result["outcomes_known"] == 2
    assert result["outcomes_unknown"] == 1
    assert result["completed_count"] == 1
    assert result["outcome_coverage"] == 2 / 3
    assert result["evidence_only"] is True


def test_missing_outcomes_are_unknown_not_failures():
    result = calibrate_historical_outcomes(
        {
            "status": "OBSERVED",
            "records": [
                {
                    "entity_id": "a",
                    "launches": [
                        {"outcome_observed": False, "outcome_status": None},
                    ],
                },
            ],
            "bounded": {},
        }
    )

    assert result["outcomes_known"] == 0
    assert result["outcomes_unknown"] == 1
    assert result["completed_count"] == 0
    assert result["outcome_coverage"] == 0.0
    assert "failure" not in result
    assert result["evidence_only"] is True


def test_empty_history_has_unknown_coverage_not_zero_coverage():
    result = calibrate_historical_outcomes(
        {"status": "OBSERVED", "records": [], "bounded": {}}
    )

    assert result["launch_count_observed"] == 0
    assert result["outcome_coverage"] is None
    assert result["evidence_only"] is True


def test_unavailable_comparison_remains_unknown():
    result = calibrate_historical_outcomes(
        {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["entity_launches"],
            "bounded": {"limit_per_entity": 20},
        }
    )

    assert result["status"] == "UNKNOWN"
    assert result["outcome_coverage"] is None
    assert result["missing"] == ["entity_launches"]
    assert result["evidence_only"] is True
