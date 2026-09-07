from stinky_api.entity_readiness_corpus_soak import evaluate_readiness_corpus_soak


def _entity(checkpoints=1, *, changed=False):
    cps = [{"status": "NOT_READY", "blockers": ["A"]}]
    if checkpoints >= 2:
        cps.append({"status": "READY" if changed else "NOT_READY", "blockers": [] if changed else ["A"]})
    return {"checkpoint_count": checkpoints, "checkpoints": cps}


def test_current_small_clean_corpus_remains_accumulating():
    report = {
        "coverage": {"entity_count": 9, "validated_entities": 0, "temporal_violation_entities": 0},
        "entities": [_entity() for _ in range(9)],
    }
    result = evaluate_readiness_corpus_soak(report)
    assert result["status"] == "ACCUMULATING_EVIDENCE"
    assert result["mature"] is False
    assert "PROSPECTIVE_COHORT_TOO_SMALL" in result["blockers"]
    assert "INSUFFICIENT_REPEAT_ENTITY_COVERAGE" in result["blockers"]
    assert "NO_VALIDATED_REPLAY_ENTITIES" in result["blockers"]
    assert result["release_authority"] is False


def test_mature_soak_requires_real_repeat_and_validated_coverage():
    entities = [_entity(2, changed=True) for _ in range(5)] + [_entity() for _ in range(20)]
    report = {"coverage": {"entity_count": 25, "validated_entities": 5, "temporal_violation_entities": 0}, "entities": entities}
    result = evaluate_readiness_corpus_soak(report)
    assert result["status"] == "SOAK_MATURE"
    assert result["mature"] is True
    assert result["blockers"] == []
    assert result["metrics"]["repeat_entities"] == 5
    assert result["metrics"]["repeat_entity_ratio"] == 0.2
    assert result["metrics"]["changed_state_entities"] == 5


def test_prospective_temporal_violation_always_fails_soak():
    entities = [_entity(2, changed=True) for _ in range(25)]
    report = {"coverage": {"entity_count": 25, "validated_entities": 25, "temporal_violation_entities": 1}, "entities": entities}
    result = evaluate_readiness_corpus_soak(report)
    assert result["status"] == "TEMPORAL_VIOLATION"
    assert result["mature"] is False
    assert "PROSPECTIVE_TEMPORAL_INTEGRITY_VIOLATION" in result["blockers"]


def test_identical_repeat_is_counted_as_depth_not_changed_state():
    report = {"coverage": {"entity_count": 1, "validated_entities": 1, "temporal_violation_entities": 0}, "entities": [_entity(2, changed=False)]}
    result = evaluate_readiness_corpus_soak(report)
    assert result["metrics"]["repeat_entities"] == 1
    assert result["metrics"]["changed_state_entities"] == 0
