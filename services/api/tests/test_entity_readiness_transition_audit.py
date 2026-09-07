from stinky_api.entity_readiness_transition_audit import (
    describe_entity_readiness_transition,
    entity_readiness_hash,
)


def _ready():
    return {
        "status": "READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": True,
        "blockers": [],
        "components": {
            "developer_history": {"status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION", "passed": True, "blockers": []},
            "relationship_history": {"status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION", "passed": True, "blockers": []},
            "outcome_history": {"status": "OBSERVED", "passed": True, "launch_count_observed": 6, "outcomes_known": 5, "outcome_coverage": 5/6},
        },
        "temporal_integrity": {"developer_cutoff_enforced": True, "relationship_cutoff_enforced": True},
        "evidence_independence": {"developer_source": "developer_longitudinal_snapshots", "relationship_source": "developer_correlation_snapshots", "outcome_source": "entity_launches", "distinct_sources": True},
        "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
    }


def _not_ready(blocker="DEVELOPER_HISTORY_NOT_STABLE"):
    row = _ready()
    row["status"] = "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION"
    row["ready"] = False
    row["blockers"] = [blocker]
    row["components"]["developer_history"] = {"status": "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION", "passed": False, "blockers": ["OUTCOME_REGIME_DRIFT"]}
    return row


def test_same_semantic_readiness_has_same_hash_despite_ordering():
    a = _not_ready()
    b = _not_ready()
    b["blockers"] = list(reversed(b["blockers"]))
    b["components"]["developer_history"]["blockers"] = list(reversed(b["components"]["developer_history"]["blockers"]))
    assert entity_readiness_hash(a) == entity_readiness_hash(b)


def test_not_ready_to_ready_is_explicit_transition():
    result = describe_entity_readiness_transition(_not_ready(), _ready())
    assert result["transition"] == "BECAME_READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["changed"] is True
    assert any(change["kind"] == "READINESS_CHANGED" for change in result["changes"])


def test_ready_to_not_ready_is_regression_not_negative_score():
    result = describe_entity_readiness_transition(_ready(), _not_ready("RELATIONSHIP_HISTORY_NOT_STABLE"))
    assert result["transition"] == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS"
    assert result["changed"] is True
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False


def test_blocker_change_without_ready_flip_is_evidence_change():
    before = _not_ready("DEVELOPER_HISTORY_NOT_STABLE")
    after = _not_ready("RELATIONSHIP_HISTORY_NOT_STABLE")
    result = describe_entity_readiness_transition(before, after)
    assert result["transition"] == "READINESS_EVIDENCE_CHANGED"
    blocker_change = next(change for change in result["changes"] if change["kind"] == "BLOCKERS_CHANGED")
    assert blocker_change["added"] == ["RELATIONSHIP_HISTORY_NOT_STABLE"]
    assert blocker_change["resolved"] == ["DEVELOPER_HISTORY_NOT_STABLE"]


def test_identical_state_is_unchanged():
    result = describe_entity_readiness_transition(_ready(), _ready())
    assert result["transition"] == "UNCHANGED"
    assert result["changed"] is False
