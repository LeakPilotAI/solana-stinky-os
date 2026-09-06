from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_discovery_engine_consumes_temporal_dataset_instead_of_requerying_history():
    source = (ROOT / "src" / "stinky_api" / "descriptive_pattern_discovery.py").read_text(encoding="utf-8")
    assert "form_pattern_discovery_dataset" in source
    assert "FROM entity_launches" not in source
    assert "market_outcome_observations" not in source
    assert "post_migration.tracking_completed" not in source


def test_discovered_patterns_preserve_dataset_and_row_provenance():
    source = (ROOT / "src" / "stinky_api" / "descriptive_pattern_discovery.py").read_text(encoding="utf-8")
    assert '"dataset_hash"' in source
    assert '"supporting_row_hashes"' in source
    assert '"pattern_hash"' in source
    assert "association_is_not_prediction" in source


def test_discovery_has_no_predictive_risk_quality_or_trade_authority():
    source = (ROOT / "src" / "stinky_api" / "descriptive_pattern_discovery.py").read_text(encoding="utf-8")
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
    assert '"risk_inferred": False' in source
    assert '"quality_inferred": False' in source
    assert '"probability_inferred": False' in source
    assert '"confidence_inferred": False' in source
    for forbidden in ("win_probability", "risk_score", "quality_score", "confidence_score", "expected_return_score", "buy_signal", "sell_signal"):
        assert forbidden not in source


def test_discovery_requires_support_and_suppresses_same_support_subset_spam():
    source = (ROOT / "src" / "stinky_api" / "descriptive_pattern_discovery.py").read_text(encoding="utf-8")
    assert "len(supporting_rows) < min_support" in source
    assert "same_support_set_keep_most_specific" in source
    assert "feature_count" in source


def test_numeric_bucketing_is_explicitly_disabled_until_governed():
    source = (ROOT / "src" / "stinky_api" / "descriptive_pattern_discovery.py").read_text(encoding="utf-8")
    assert '"numeric_bucketing_enabled": False' in source
    assert "isinstance(value, bool) or isinstance(value, str)" in source


def test_command_center_hot_poll_is_not_coupled_to_pattern_discovery():
    main_source = (ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "discover_patterns_from_history" not in main_source
    assert "descriptive_pattern_discovery" not in main_source
