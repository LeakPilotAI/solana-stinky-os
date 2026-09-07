from stinky_api.entity_readiness_component_maturity import summarize_readiness_component_maturity


def _row(*, developer=False, relationship=False, outcome=False, outcome_status="UNKNOWN", launches=0, known=0, coverage=None):
    blockers = []
    if not developer:
        blockers.append("DEVELOPER_HISTORY_NOT_STABLE")
    if not relationship:
        blockers.append("RELATIONSHIP_HISTORY_NOT_STABLE")
    if outcome_status != "OBSERVED":
        blockers.append("OUTCOME_HISTORY_UNAVAILABLE")
    return {
        "status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": False,
        "blockers": blockers,
        "components": {
            "developer_history": {"status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if developer else "NOT_EVALUATED", "passed": developer, "blockers": [] if developer else ["READINESS_GATE_NOT_PASSED"]},
            "relationship_history": {"status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if relationship else "NOT_EVALUATED", "passed": relationship, "blockers": [] if relationship else ["READINESS_GATE_NOT_PASSED"]},
            "outcome_history": {"status": outcome_status, "passed": outcome, "blockers": [], "launch_count_observed": launches, "outcomes_known": known, "outcome_coverage": coverage},
        },
    }


def test_component_maturity_counts_real_latest_states_without_authority():
    result = summarize_readiness_component_maturity([
        _row(outcome_status="UNKNOWN"),
        _row(developer=True, outcome_status="OBSERVED", launches=7, known=4, coverage=4 / 7),
        _row(developer=True, relationship=True, outcome=True, outcome_status="OBSERVED", launches=8, known=6, coverage=0.75),
    ])

    assert result["status"] == "MEASURED"
    assert result["entity_count"] == 3
    assert result["top_level_blocker_counts"]["DEVELOPER_HISTORY_NOT_STABLE"] == 1
    assert result["top_level_blocker_counts"]["RELATIONSHIP_HISTORY_NOT_STABLE"] == 2
    assert result["top_level_blocker_counts"]["OUTCOME_HISTORY_UNAVAILABLE"] == 1
    assert result["components"]["developer_history"]["passed_entities"] == 2
    assert result["components"]["relationship_history"]["passed_entities"] == 1
    assert result["components"]["outcome_history"]["passed_entities"] == 1
    assert result["outcome_history_metrics"]["observed_entities"] == 2
    assert result["outcome_history_metrics"]["max_launch_count_observed"] == 8
    assert result["outcome_history_metrics"]["max_outcomes_known"] == 6
    assert result["outcome_history_metrics"]["max_outcome_coverage"] == 0.75
    assert result["predictive_authority"] is False
    assert result["release_authority"] is False
    assert result["trade_signal"] is False


def test_component_maturity_empty_cohort_fails_closed():
    result = summarize_readiness_component_maturity([])
    assert result["status"] == "INSUFFICIENT_CAPTURED_HISTORY"
    assert result["entity_count"] == 0
    assert result["components"]["developer_history"]["passed_ratio"] is None
    assert result["outcome_history_metrics"]["max_outcome_coverage"] is None
    assert result["release_authority"] is False
