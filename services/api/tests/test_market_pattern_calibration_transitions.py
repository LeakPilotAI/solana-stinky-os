from stinky_api.market_pattern_calibration_transitions import describe_calibration_state_transitions


def _record(snapshot_id, state, day):
    return {
        "id": snapshot_id,
        "pattern_hash": "pattern-1",
        "trend_status": state,
        "evidence_through_observed_at": f"2026-09-{day:02d}T00:00:00Z",
    }


def test_collapses_snapshots_into_runs_and_transitions():
    memory = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [
            _record(1, "STABLE", 1),
            _record(2, "STABLE", 2),
            _record(3, "DEGRADING", 3),
            _record(4, "DEGRADING", 4),
            _record(5, "IMPROVING", 5),
            _record(6, "STABLE", 6),
        ],
        "evidence_only": True,
    }
    result = describe_calibration_state_transitions(memory)

    assert result["status"] == "OBSERVED"
    assert result["current_state"] == "STABLE"
    assert result["snapshot_count"] == 6
    assert result["state_run_count"] == 4
    assert result["transition_count"] == 3
    assert [run["state"] for run in result["state_runs"]] == ["STABLE", "DEGRADING", "IMPROVING", "STABLE"]
    assert result["state_runs"][0]["snapshot_count"] == 2
    assert result["transitions"][0]["transition"] == "STABLE->DEGRADING"
    assert result["transitions"][1]["transition"] == "DEGRADING->IMPROVING"
    assert result["degradation_episode_count"] == 1
    assert result["recovered_degradation_episode_count"] == 1
    assert result["open_degradation_episode"] is False
    assert result["evidence_only"] is True
    assert all(k not in result for k in ("prediction", "probability", "confidence", "risk", "quality", "trade_signal"))


def test_open_degradation_episode_remains_descriptive():
    memory = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [_record(1, "STABLE", 1), _record(2, "DEGRADING", 2), _record(3, "DEGRADING", 3)],
    }
    result = describe_calibration_state_transitions(memory)
    assert result["current_state"] == "DEGRADING"
    assert result["degradation_episode_count"] == 1
    assert result["recovered_degradation_episode_count"] == 0
    assert result["open_degradation_episode"] is True


def test_chronology_is_evidence_time_not_input_order():
    memory = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [_record(3, "IMPROVING", 3), _record(1, "STABLE", 1), _record(2, "DEGRADING", 2)],
    }
    result = describe_calibration_state_transitions(memory)
    assert [t["transition"] for t in result["transitions"]] == ["STABLE->DEGRADING", "DEGRADING->IMPROVING"]


def test_invalid_snapshots_fail_closed():
    result = describe_calibration_state_transitions({
        "status": "OBSERVED", "pattern_hash": "pattern-1",
        "records": [{"trend_status": "MADE_UP", "evidence_through_observed_at": "2026-09-01T00:00:00Z"}],
    })
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["valid_calibration_snapshot_states"]


def test_temporal_cutoff_provenance_is_preserved():
    memory = {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "records": [_record(1, "STABLE", 1)],
        "as_of": "2026-09-02T00:00:00+00:00",
        "temporal_cutoff_enforced": True,
    }
    result = describe_calibration_state_transitions(memory)
    assert result["as_of"] == memory["as_of"]
    assert result["temporal_cutoff_enforced"] is True
