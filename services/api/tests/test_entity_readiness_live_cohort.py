import pytest

from stinky_api.entity_readiness_live_cohort import (
    live_entity_readiness_cohort_validation,
    summarize_live_cohort_replay,
)


def _entity(status="VALIDATED", *, ready=False, regressions=0):
    return {
        "status": status,
        "ready_checkpoint_count": 1 if ready else 0,
        "regression_count": regressions,
        "checkpoints": [{"ready": ready}],
    }


def test_summary_reports_live_coverage_without_release_authority():
    result = summarize_live_cohort_replay({
        "entities": [
            _entity(ready=True),
            _entity(ready=False, regressions=1),
            _entity("INSUFFICIENT_CAPTURED_HISTORY"),
        ]
    })
    assert result["status"] == "MEASURED"
    assert result["coverage"]["entity_count"] == 3
    assert result["coverage"]["validated_entities"] == 2
    assert result["coverage"]["validated_ratio"] == pytest.approx(2 / 3)
    assert result["coverage"]["insufficient_history_entities"] == 1
    assert result["coverage"]["currently_ready_entities"] == 1
    assert result["coverage"]["entities_with_regressions"] == 1
    assert "CAPTURED_HISTORY_COVERAGE_INCOMPLETE" in result["blockers"]
    assert result["release_gate"]["status"] == "NOT_AUTHORIZED"
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False
    assert result["read_only"] is True


def test_summary_fails_closed_when_temporal_violations_exist():
    result = summarize_live_cohort_replay({
        "entities": [_entity(), _entity("TEMPORAL_VIOLATION")]
    })
    assert result["status"] == "TEMPORAL_VIOLATION"
    assert result["measurement_complete"] is False
    assert result["coverage"]["temporal_violation_entities"] == 1
    assert "TEMPORAL_INTEGRITY_VIOLATIONS_PRESENT" in result["blockers"]


def test_empty_cohort_is_insufficient_not_zero_quality():
    result = summarize_live_cohort_replay({"entities": []})
    assert result["status"] == "INSUFFICIENT_CAPTURED_HISTORY"
    assert result["coverage"]["entity_count"] == 0
    assert result["coverage"]["validated_ratio"] is None
    assert "NO_CAPTURED_ENTITY_COHORT" in result["blockers"]
    assert result["quality_inferred"] is False


@pytest.mark.asyncio
async def test_live_measurement_delegates_to_bounded_replay(monkeypatch):
    captured = {}

    async def fake_replay(session, **kwargs):
        captured.update(kwargs)
        return {
            "status": "VALIDATED",
            "valid": True,
            "entities": [_entity(ready=True), _entity(ready=False)],
            "bounded": {"entity_limit": 25, "snapshot_limit_per_entity": 30},
            "historical_policy": {"captured_snapshots_only": True, "derived_snapshots_are_not_backdated": True},
            "as_of": "2026-09-01T00:00:00+00:00",
            "temporal_cutoff_enforced": True,
        }

    monkeypatch.setattr("stinky_api.entity_readiness_live_cohort.historical_entity_readiness_replay", fake_replay)
    result = await live_entity_readiness_cohort_validation(
        object(), entity_limit=25, snapshot_limit_per_entity=30,
        as_of="2026-09-01T00:00:00Z", include_entities=True,
    )
    assert captured["entity_limit"] == 25
    assert captured["snapshot_limit_per_entity"] == 30
    assert captured["as_of"] == "2026-09-01T00:00:00Z"
    assert result["coverage"]["validated_entities"] == 2
    assert len(result["entities"]) == 2
    assert result["bounded"] == {"entity_limit": 25, "snapshot_limit_per_entity": 30}
    assert result["temporal_cutoff_enforced"] is True
