from datetime import datetime, timezone

from stinky_api.market_pattern_calibration_synthesis_audit import (
    describe_synthesis_change,
    synthesis_hash,
)


def _summary(**overrides):
    base = {
        "status": "OBSERVED",
        "pattern_hash": "abc",
        "evidence_status": "PARTIAL_EVIDENCE",
        "chain_status": {"rolling": "OBSERVED"},
        "observed_layer_count": 1,
        "layer_count": 7,
        "current_calibration_state": "INSUFFICIENT_EVIDENCE",
        "transition_count": 0,
        "open_degradation_episode": False,
        "regime_memory": {"pattern_count": 2, "state_counts": {"STABLE": 1, "DEGRADING": 1}},
        "historical_segmentation": {"segmented_occurrence_count": 2, "regime_counts": {"MIXED": 2}},
        "conditional_evidence": {"sufficient_regimes": [], "sufficient_regime_count": 0},
        "chronological_generalization": {
            "stable_regimes": [],
            "unstable_regimes": [],
            "insufficient_regimes": ["MIXED"],
        },
        "missing": ["market_pattern_followup_evidence"],
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }
    base.update(overrides)
    return base


def test_hash_is_deterministic_and_ignores_unrelated_fields():
    a = _summary()
    b = dict(a)
    b["debug"] = {"ignored": True}
    assert synthesis_hash(a) == synthesis_hash(b)


def test_initial_snapshot_is_not_claimed_as_change():
    change = describe_synthesis_change(None, _summary())
    assert change["status"] == "INITIAL_SNAPSHOT"
    assert change["changed"] is False
    assert change["predictive_authority"] is False
    assert change["trade_signal"] is False


def test_unknown_resolution_and_state_transition_are_described_factually():
    previous = _summary()
    current = _summary(
        evidence_status="COMPLETE_OBSERVED_CHAIN",
        observed_layer_count=7,
        current_calibration_state="STABLE",
        transition_count=1,
        missing=[],
    )
    change = describe_synthesis_change(previous, current)
    assert change["status"] == "CHANGED"
    assert change["changed"] is True
    kinds = [item["kind"] for item in change["changes"]]
    assert "UNKNOWN_RESOLVED" in kinds
    fields = {item.get("field") for item in change["changes"] if item.get("kind") == "FIELD_CHANGED"}
    assert "current_calibration_state" in fields
    assert "transition_count" in fields


def test_regime_and_generalization_sets_are_diffed_without_directional_judgment():
    previous = _summary()
    current = _summary(
        regime_memory={"pattern_count": 3, "state_counts": {"STABLE": 2, "DEGRADING": 1}},
        conditional_evidence={"sufficient_regimes": ["STABLE_DOMINANT"], "sufficient_regime_count": 1},
        chronological_generalization={
            "stable_regimes": ["STABLE_DOMINANT"],
            "unstable_regimes": [],
            "insufficient_regimes": [],
        },
    )
    change = describe_synthesis_change(previous, current)
    kinds = [item["kind"] for item in change["changes"]]
    assert "REGIME_STATE_COUNTS_CHANGED" in kinds
    assert kinds.count("SET_CHANGED") >= 2
    forbidden = {"score", "confidence", "probability", "risk", "quality", "expected_return", "trade_direction"}
    assert forbidden.isdisjoint(change.keys())
    assert change["shared_cause_inferred"] is False


def test_identical_summary_is_unchanged():
    summary = _summary(as_of=datetime(2026, 9, 6, tzinfo=timezone.utc).isoformat())
    change = describe_synthesis_change(summary, dict(summary))
    assert change["status"] == "UNCHANGED"
    assert change["changes"] == []
