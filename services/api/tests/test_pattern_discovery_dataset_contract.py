from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dataset_uses_persisted_temporal_snapshots_and_immutable_labels():
    source = (ROOT / "src" / "stinky_api" / "pattern_discovery_dataset.py").read_text(encoding="utf-8")
    assert "developer_longitudinal_snapshots" in source
    assert "developer_correlation_snapshots" in source
    assert "post_migration.tracking_completed" in source
    assert "s.observed_at <= l.observed_at + make_interval" in source
    assert "s.ingested_at <= l.observed_at + make_interval" in source
    assert "o.observed_at <= l.observed_at + make_interval" in source
    assert "o.ingested_at <= l.observed_at + make_interval" in source


def test_dataset_is_bounded_and_not_n_plus_one():
    source = (ROOT / "src" / "stinky_api" / "pattern_discovery_dataset.py").read_text(encoding="utf-8")
    assert "limit = max(1, min(500" in source
    assert '"query_count": 3 if mints else 1' in source
    assert "o.mint = ANY(:mints)" in source
    assert "e.payload->>'mint' = ANY(:mints)" in source


def test_dataset_has_no_prediction_risk_quality_or_trade_authority():
    source = (ROOT / "src" / "stinky_api" / "pattern_discovery_dataset.py").read_text(encoding="utf-8").lower()
    for forbidden in ("win_probability", "buy_signal", "risk_score", "quality_score", "expected_return_score", "confidence_score"):
        assert forbidden not in source
    assert '"pattern_discovery_authority": false' in source
    assert '"predictive_authority": false' in source
    assert '"trade_signal": false' in source


def test_command_center_does_not_import_pattern_discovery_dataset():
    main = (ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "pattern_discovery_dataset" not in main
