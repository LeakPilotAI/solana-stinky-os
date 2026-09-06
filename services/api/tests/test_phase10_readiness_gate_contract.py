from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase10_gate_is_fail_closed_descriptive_only_and_not_command_center_coupled():
    source = (ROOT / "src" / "stinky_api" / "phase10_readiness_gate.py").read_text(encoding="utf-8")
    assert '"PHASE_10_COMPLETE" if complete else "NOT_READY_FOR_PHASE_11"' in source
    assert '"phase_11_authorized": False' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
    assert '"probability_inferred": False' in source
    assert '"confidence_inferred": False' in source
    assert "command-center" not in source.lower()
    assert "command_center" not in source.lower()


def test_phase10_gate_requires_identity_temporal_and_unknown_integrity_contracts():
    source = (ROOT / "src" / "stinky_api" / "phase10_readiness_gate.py").read_text(encoding="utf-8")
    for criterion in (
        "row_hash_integrity",
        "unknown_outcome_preservation",
        "pattern_hash_integrity",
        "discovery_dataset_identity",
        "validation_dataset_identity",
        "validation_pattern_identity",
        "persistence_pattern_identity",
        "dual_temporal_replay",
    ):
        assert criterion in source
    assert "observed_at <= :as_of" in source
    assert "ingested_at <= :as_of" in source
    assert "COUNT(*)::int AS snapshot_count" in source
