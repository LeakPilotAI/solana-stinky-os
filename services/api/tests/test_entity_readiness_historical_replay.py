from stinky_api.entity_readiness_historical_replay import validate_entity_readiness_replay


def _readiness(ready: bool, blocker: str | None = None):
    blockers = [blocker] if blocker else []
    status = "READY_FOR_DESCRIPTIVE_CALIBRATION" if ready else "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION"
    stable = "STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    return {
        "status": status,
        "ready": ready,
        "blockers": blockers,
        "components": {
            "developer_history": {"status": stable, "passed": True, "blockers": []},
            "relationship_history": {"status": stable if ready else "INSUFFICIENT_HISTORY", "passed": ready, "blockers": blockers},
            "outcome_history": {"status": "OBSERVED", "passed": True, "launch_count_observed": 6, "outcomes_known": 5, "outcome_coverage": 5 / 6},
        },
        "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }


def _record(day: int, readiness, *, ingested_day: int | None = None):
    ingested_day = day if ingested_day is None else ingested_day
    return {
        "observed_at": f"2026-08-{day:02d}T12:00:00Z",
        "ingested_at": f"2026-08-{ingested_day:02d}T12:01:00Z",
        "readiness": readiness,
    }


def test_replay_validates_ready_transition_and_regression_without_authority():
    result = validate_entity_readiness_replay([
        _record(1, _readiness(False, "RELATIONSHIP_HISTORY_NOT_STABLE")),
        _record(10, _readiness(True)),
        _record(20, _readiness(False, "RELATIONSHIP_HISTORY_NOT_STABLE")),
    ])
    assert result["status"] == "VALIDATED"
    assert result["became_ready_count"] == 1
    assert result["regression_count"] == 1
    assert result["checkpoints"][1]["transition"] == "BECAME_READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["checkpoints"][2]["transition"] == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS"
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False


def test_replay_keeps_single_snapshot_as_insufficient_captured_history():
    result = validate_entity_readiness_replay([_record(1, _readiness(False, "DEVELOPER_HISTORY_NOT_STABLE"))])
    assert result["status"] == "INSUFFICIENT_CAPTURED_HISTORY"
    assert result["blockers"] == ["INSUFFICIENT_REPLAY_DEPTH"]
    assert result["historical_policy"]["missing_history_remains_unknown"] is True
    assert result["historical_snapshot_reconstruction_authorized"] is False


def test_replay_fails_closed_on_invalid_or_impossible_capture_times():
    bad = _record(10, _readiness(True), ingested_day=9)
    result = validate_entity_readiness_replay([bad, _record(20, _readiness(True))])
    assert result["status"] == "TEMPORAL_VIOLATION"
    assert result["valid"] is False
    assert "INGESTED_BEFORE_OBSERVED" in result["blockers"]


def test_as_of_excludes_future_snapshot_and_future_ingestion():
    records = [
        _record(1, _readiness(False, "RELATIONSHIP_HISTORY_NOT_STABLE")),
        _record(10, _readiness(True)),
        _record(20, _readiness(False, "RELATIONSHIP_HISTORY_NOT_STABLE")),
        {"observed_at": "2026-08-11T12:00:00Z", "ingested_at": "2026-08-25T12:00:00Z", "readiness": _readiness(False, "DEVELOPER_HISTORY_NOT_STABLE")},
    ]
    result = validate_entity_readiness_replay(records, as_of="2026-08-15T00:00:00Z")
    assert result["status"] == "VALIDATED"
    assert result["checkpoint_count"] == 2
    assert result["regression_count"] == 0
    assert result["temporal_integrity"]["future_snapshots_excluded"] == 2
    assert result["as_of"] == "2026-08-15T00:00:00+00:00"


def test_invalid_as_of_fails_closed():
    result = validate_entity_readiness_replay([_record(1, _readiness(True))], as_of="not-a-time")
    assert result["status"] == "TEMPORAL_VIOLATION"
    assert result["blockers"] == ["INVALID_AS_OF"]
