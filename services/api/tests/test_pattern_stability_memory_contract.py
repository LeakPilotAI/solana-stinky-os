from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pattern_stability_memory_is_descriptive_and_temporally_safe():
    source = (ROOT / "src" / "stinky_api" / "pattern_stability_memory.py").read_text(encoding="utf-8")
    assert "pattern_stability_snapshots" in source
    assert "UNIQUE (pattern_hash, evidence_hash)" in source
    assert "observed_at <= :as_of AND ingested_at <= :as_of" in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
    assert '"probability_inferred": False' in source
    assert '"confidence_inferred": False' in source
    assert '"expected_return_inferred": False' in source


def test_pattern_stability_memory_tracks_state_transitions_not_predictions():
    source = (ROOT / "src" / "stinky_api" / "pattern_stability_memory.py").read_text(encoding="utf-8")
    assert "STABILITY_STATE_CHANGED" in source
    assert "SUPPORT_COUNT_CHANGED" in source
    assert "OUTCOME_DRIFT_CHANGED" in source
    assert "DATASET_CHANGED" in source
    forbidden = ("buy_signal", "sell_signal", "expected_return_score", "risk_score", "quality_score")
    for token in forbidden:
        assert token not in source
