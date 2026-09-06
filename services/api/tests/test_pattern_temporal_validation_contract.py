from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_temporal_validation_reuses_safe_dataset_tokens_and_does_not_query_database():
    source = (ROOT / "src" / "stinky_api" / "pattern_temporal_validation.py").read_text(encoding="utf-8")
    assert "extract_discrete_feature_tokens" in source
    assert "from sqlalchemy" not in source
    assert "session.execute" not in source


def test_validation_has_chronological_split_and_rolling_windows():
    source = (ROOT / "src" / "stinky_api" / "pattern_temporal_validation.py").read_text(encoding="utf-8")
    assert '"method": "chronological_halves"' in source
    assert "rolling_window_size" in source
    assert "rolling_step" in source
    assert "max_outcome_drift_pct_points" in source


def test_validation_preserves_unknown_and_requires_label_coverage():
    source = (ROOT / "src" / "stinky_api" / "pattern_temporal_validation.py").read_text(encoding="utf-8")
    assert '"UNKNOWN"' in source
    assert "known_label_coverage" in source
    assert "min_known_label_coverage" in source
    assert '"INSUFFICIENT_EVIDENCE"' in source


def test_validation_does_not_introduce_prediction_or_trading_authority():
    source = (ROOT / "src" / "stinky_api" / "pattern_temporal_validation.py").read_text(encoding="utf-8").lower()
    for forbidden in ("buy_signal", "sell_signal", "expected_return_score", "win_probability", "risk_score", "quality_score"):
        assert forbidden not in source
    assert '"predictive_authority": false' in source
    assert '"trade_signal": false' in source
    assert '"probability_inferred": false' in source
    assert '"confidence_inferred": false' in source


def test_command_center_does_not_import_pattern_temporal_validation():
    source = (ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "pattern_temporal_validation" not in source
