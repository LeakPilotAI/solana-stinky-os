from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_analogue_loader_is_bulk_bounded_not_n_plus_one():
    source = (ROOT / "src" / "stinky_api" / "lifecycle_analogue_distribution.py").read_text(encoding="utf-8")
    assert "mint_limit = max(1, min(200" in source or "bounded = max(1, min(200" in source
    assert '"query_count": 2' in source
    assert "WHERE o.mint = ANY(:mints)" in source
    assert "e.payload->>'mint' = ANY(:mints)" in source


def test_motif_analogue_context_uses_lifecycle_memory_and_not_mutable_outcome_field():
    source = (ROOT / "src" / "stinky_api" / "developer_motif_outcome_context.py").read_text(encoding="utf-8")
    assert "load_lifecycle_memories_for_mints" in source
    assert '"lifecycle_distribution"' in source
    assert "l.outcome_status" not in source
    assert "analogue_history_is_not_prediction" in source


def test_no_prediction_or_trade_authority_is_introduced():
    source = (ROOT / "src" / "stinky_api" / "lifecycle_analogue_distribution.py").read_text(encoding="utf-8").lower()
    for forbidden in ("risk_score", "quality_score", "confidence_score", "expected_return_score", "win_probability", "buy_signal"):
        assert forbidden not in source
    assert '"predictive_authority": false' in source
    assert '"trade_signal": false' in source


def test_command_center_hot_poll_entrypoint_is_not_coupled_to_lifecycle_analogue_queries():
    api_main = (ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "lifecycle_analogue_distribution" not in api_main
    assert "load_lifecycle_memories_for_mints" not in api_main
