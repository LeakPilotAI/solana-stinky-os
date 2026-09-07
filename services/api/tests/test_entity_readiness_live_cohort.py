import pytest

from stinky_api.entity_readiness_live_cohort import (
    PROSPECTIVE_CAPTURE_EPOCH,
    _historical_integrity_summary,
    live_entity_readiness_cohort_validation,
    summarize_live_cohort_replay,
)


def _entity(status="VALIDATED", *, ready=False, regressions=0, entity_id=None):
    result = {
        "status": status,
        "ready_checkpoint_count": 1 if ready else 0,
        "regression_count": regressions,
        "checkpoints": [{"ready": ready}],
    }
    if entity_id is not None:
        result["entity_id"] = entity_id
    return result


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


def test_historical_integrity_quarantines_legacy_only_violations_but_not_future_ones():
    historical = {
        "status": "TEMPORAL_VIOLATION",
        "valid": False,
        "entities": [
            _entity("TEMPORAL_VIOLATION", entity_id="legacy"),
            _entity("TEMPORAL_VIOLATION", entity_id="future-bad"),
            _entity("INSUFFICIENT_CAPTURED_HISTORY", entity_id="clean"),
        ],
    }
    prospective = {
        "status": "TEMPORAL_VIOLATION",
        "valid": False,
        "entities": [
            _entity("TEMPORAL_VIOLATION", entity_id="future-bad"),
            _entity("INSUFFICIENT_CAPTURED_HISTORY", entity_id="clean"),
        ],
    }
    result = _historical_integrity_summary(historical, prospective, include_entities=True)
    assert result["temporal_violation_entities"] == 2
    assert result["prospective_temporal_violation_entities"] == 1
    assert result["legacy_temporal_violation_entities"] == 1
    assert result["legacy_temporal_violation_entity_ids"] == ["legacy"]
    assert result["legacy_rows_preserved"] is True
    assert result["legacy_rows_mutated"] is False
    assert result["prospective_violations_fail_live_health"] is True


@pytest.mark.asyncio
async def test_live_measurement_separates_whole_history_from_prospective_epoch(monkeypatch):
    calls = []

    async def fake_replay(session, **kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("not_before") is None:
            return {
                "status": "TEMPORAL_VIOLATION",
                "valid": False,
                "entities": [
                    _entity("TEMPORAL_VIOLATION", entity_id="legacy"),
                    _entity("INSUFFICIENT_CAPTURED_HISTORY", entity_id="clean"),
                ],
                "bounded": {"entity_limit": 25, "snapshot_limit_per_entity": 30},
                "historical_policy": {"captured_snapshots_only": True, "derived_snapshots_are_not_backdated": True},
                "as_of": "2026-09-08T00:00:00+00:00",
                "temporal_cutoff_enforced": True,
            }
        assert kwargs["not_before"] == PROSPECTIVE_CAPTURE_EPOCH
        return {
            "status": "INSUFFICIENT_CAPTURED_HISTORY",
            "valid": False,
            "entities": [_entity("INSUFFICIENT_CAPTURED_HISTORY", entity_id="clean")],
            "bounded": {"entity_limit": 25, "snapshot_limit_per_entity": 30},
            "historical_policy": {"captured_snapshots_only": True, "derived_snapshots_are_not_backdated": True},
            "as_of": "2026-09-08T00:00:00+00:00",
            "temporal_cutoff_enforced": True,
        }

    monkeypatch.setattr("stinky_api.entity_readiness_live_cohort.historical_entity_readiness_replay", fake_replay)
    result = await live_entity_readiness_cohort_validation(
        object(), entity_limit=25, snapshot_limit_per_entity=30,
        as_of="2026-09-08T00:00:00Z", include_entities=True,
    )
    assert len(calls) == 2
    assert calls[0]["entity_limit"] == 25
    assert calls[0]["not_before"] if "not_before" in calls[0] else None is None
    assert calls[1]["not_before"] == PROSPECTIVE_CAPTURE_EPOCH
    assert result["status"] == "MEASURED"
    assert result["measurement_complete"] is True
    assert result["coverage"]["entity_count"] == 1
    assert result["coverage"]["temporal_violation_entities"] == 0
    assert result["coverage"]["insufficient_history_entities"] == 1
    assert result["historical_integrity"]["temporal_violation_entities"] == 1
    assert result["historical_integrity"]["legacy_temporal_violation_entities"] == 1
    assert result["historical_integrity"]["legacy_temporal_violation_entity_ids"] == ["legacy"]
    assert result["prospective_epoch"] == PROSPECTIVE_CAPTURE_EPOCH.isoformat()
    assert result["cohort_scope"] == "POST_TIMESTAMP_INTEGRITY_FIX_PROSPECTIVE_CAPTURE"
    assert len(result["entities"]) == 1


@pytest.mark.asyncio
async def test_post_epoch_temporal_violation_still_fails_live_health(monkeypatch):
    async def fake_replay(session, **kwargs):
        if kwargs.get("not_before") is None:
            return {
                "status": "TEMPORAL_VIOLATION",
                "valid": False,
                "entities": [_entity("TEMPORAL_VIOLATION", entity_id="future-bad")],
            }
        return {
            "status": "TEMPORAL_VIOLATION",
            "valid": False,
            "entities": [_entity("TEMPORAL_VIOLATION", entity_id="future-bad")],
        }

    monkeypatch.setattr("stinky_api.entity_readiness_live_cohort.historical_entity_readiness_replay", fake_replay)
    result = await live_entity_readiness_cohort_validation(object())
    assert result["status"] == "TEMPORAL_VIOLATION"
    assert result["measurement_complete"] is False
    assert result["coverage"]["temporal_violation_entities"] == 1
    assert result["historical_integrity"]["prospective_temporal_violation_entities"] == 1
    assert result["historical_integrity"]["legacy_temporal_violation_entities"] == 0
