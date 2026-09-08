from datetime import datetime, timezone

import pytest

from stinky_api.entity_readiness_component_maturity import (
    readiness_component_maturity,
    summarize_persisted_outcomes,
    summarize_readiness_component_maturity,
)


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


def test_persisted_outcomes_count_canonical_labels_and_unknown_reasons():
    rows = [
        {
            "entity_id": "e1",
            "outcome_status": "RUNNER",
            "outcome_meta": {
                "evidence_basis": "durable_completed_market_path_classification",
                "classification": {
                    "canonical_classification": True,
                    "reason": "peak_multiple_met",
                    "evidence_basis": "completed_market_snapshot_path",
                },
            },
        },
        {
            "entity_id": "e2",
            "outcome_status": "FADE",
            "outcome_meta": {
                "evidence_basis": "durable_completed_market_path_classification",
                "classification": {
                    "canonical_classification": True,
                    "reason": "drawdown_fade",
                },
            },
        },
        {
            "entity_id": "e3",
            "outcome_status": "completed",
            "outcome_meta": {
                "performance_outcome": "UNKNOWN",
                "classification": {"reason": "insufficient_measured_price_path"},
            },
        },
        {"entity_id": "e4", "outcome_status": None, "outcome_meta": {}},
    ]

    result = summarize_persisted_outcomes(rows)

    assert result["status"] == "MEASURED"
    assert result["launch_status_counts"] == {"FADE": 1, "NULL": 1, "RUNNER": 1, "COMPLETED": 1}
    assert result["canonical_classified_launches"] == 2
    assert result["entities_with_canonical_classification"] == 2
    assert result["unknown_performance_launches"] == 1
    assert result["classification_reason_counts"]["peak_multiple_met"] == 1
    assert result["classification_reason_counts"]["drawdown_fade"] == 1
    assert result["classification_reason_counts"]["insufficient_measured_price_path"] == 1
    assert result["evidence_basis_counts"]["durable_completed_market_path_classification"] == 2
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


class _MappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, result_sets):
        self._result_sets = list(result_sets)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _MappingsResult(self._result_sets.pop(0))


@pytest.mark.asyncio
async def test_live_component_diagnostic_reads_persisted_launch_outcomes():
    readiness = _row(outcome_status="UNKNOWN")
    session = _Session([
        [{"readiness": readiness}],
        [{
            "entity_id": "00000000-0000-0000-0000-000000000001",
            "mint": "MintMeasured",
            "observed_at": datetime(2026, 9, 8, tzinfo=timezone.utc),
            "outcome_status": "HELD",
            "outcome_meta": {
                "evidence_basis": "durable_completed_market_path_classification",
                "classification": {
                    "canonical_classification": True,
                    "reason": "held_within_drawdown",
                },
            },
        }],
    ])

    result = await readiness_component_maturity(
        session,
        entity_ids=["00000000-0000-0000-0000-000000000001"],
        not_before=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )

    assert result["components"]["outcome_history"]["status_counts"] == {"UNKNOWN": 1}
    assert result["persisted_outcomes"]["launch_status_counts"] == {"HELD": 1}
    assert result["persisted_outcomes"]["canonical_classified_launches"] == 1
    assert "FROM entity_launches" in session.calls[1][0]
    assert result["persisted_outcomes"]["release_authority"] is False


@pytest.mark.asyncio
async def test_historical_as_of_does_not_reconstruct_mutable_persisted_outcomes():
    session = _Session([[{"readiness": _row(outcome_status="UNKNOWN")} ]])
    cutoff = datetime(2026, 9, 8, tzinfo=timezone.utc)

    result = await readiness_component_maturity(
        session,
        entity_ids=["00000000-0000-0000-0000-000000000001"],
        not_before=datetime(2026, 9, 7, tzinfo=timezone.utc),
        as_of=cutoff,
    )

    assert result["persisted_outcomes"]["status"] == "HISTORICAL_OUTCOME_STATE_UNAVAILABLE"
    assert result["persisted_outcomes"]["historical_as_of_supported"] is False
    assert len(session.calls) == 1
