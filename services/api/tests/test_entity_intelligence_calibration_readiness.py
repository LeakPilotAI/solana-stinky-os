from stinky_api.entity_intelligence_calibration_readiness import assess_entity_intelligence_calibration_readiness


def _developer(stable=True, cutoff=True):
    return {
        "stable": stable,
        "stability_status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if stable else "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION",
        "blockers": [] if stable else ["OUTCOME_REGIME_DRIFT"],
        "source": "developer_longitudinal_snapshots",
        "temporal_cutoff_enforced": cutoff,
    }


def _relationship(stable=True, cutoff=True):
    return {
        "stable": stable,
        "stability_status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if stable else "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION",
        "blockers": [] if stable else ["NO_CROSS_WINDOW_RECURRENCE"],
        "source": "developer_correlation_snapshots",
        "temporal_cutoff_enforced": cutoff,
    }


def _outcomes(launches=6, known=5, coverage=5 / 6, status="OBSERVED"):
    return {
        "status": status,
        "launch_count_observed": launches,
        "outcomes_known": known,
        "outcomes_unknown": max(0, launches - known),
        "outcome_coverage": coverage,
        "evidence_basis": "entity_launches",
        "evidence_only": True,
    }


def test_combined_gate_ready_only_when_all_components_pass():
    result = assess_entity_intelligence_calibration_readiness(_developer(), _relationship(), _outcomes())
    assert result["status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["evidence_independence"]["distinct_sources"] is True
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False


def test_unstable_developer_history_blocks_entity_readiness():
    result = assess_entity_intelligence_calibration_readiness(_developer(False), _relationship(), _outcomes())
    assert result["ready"] is False
    assert "DEVELOPER_HISTORY_NOT_STABLE" in result["blockers"]


def test_unstable_relationship_history_blocks_entity_readiness():
    result = assess_entity_intelligence_calibration_readiness(_developer(), _relationship(False), _outcomes())
    assert result["ready"] is False
    assert "RELATIONSHIP_HISTORY_NOT_STABLE" in result["blockers"]


def test_outcome_history_requires_depth_known_count_and_coverage():
    result = assess_entity_intelligence_calibration_readiness(_developer(), _relationship(), _outcomes(launches=4, known=2, coverage=0.5))
    assert result["ready"] is False
    assert "INSUFFICIENT_OUTCOME_LAUNCHES" in result["blockers"]
    assert "INSUFFICIENT_KNOWN_OUTCOMES" in result["blockers"]
    assert "INSUFFICIENT_OUTCOME_COVERAGE" in result["blockers"]


def test_unknown_outcome_history_fails_closed():
    result = assess_entity_intelligence_calibration_readiness(_developer(), _relationship(), _outcomes(status="UNKNOWN", launches=0, known=0, coverage=None))
    assert result["ready"] is False
    assert "OUTCOME_HISTORY_UNAVAILABLE" in result["blockers"]


def test_as_of_requires_temporal_integrity_from_both_history_components():
    result = assess_entity_intelligence_calibration_readiness(
        _developer(cutoff=True), _relationship(cutoff=False), _outcomes(), as_of="2026-09-01T00:00:00+00:00"
    )
    assert result["ready"] is False
    assert "TEMPORAL_INTEGRITY_NOT_ESTABLISHED" in result["blockers"]
    assert result["temporal_cutoff_enforced"] is False


def test_non_independent_sources_fail_closed():
    developer = _developer()
    relationship = _relationship()
    relationship["source"] = "developer_longitudinal_snapshots"
    result = assess_entity_intelligence_calibration_readiness(developer, relationship, _outcomes())
    assert result["ready"] is False
    assert "EVIDENCE_INDEPENDENCE_NOT_ESTABLISHED" in result["blockers"]
