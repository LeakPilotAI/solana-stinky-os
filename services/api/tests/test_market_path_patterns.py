from stinky_api.market_path_patterns import discover_market_path_patterns


def _analysis(change):
    return {"status": "OBSERVED", "observed_horizons": ["5m", "15m"], "observed_record_count": 2,
            "metrics": {"price_usd": {"first": {"horizon": "5m", "value": 1.0},
            "last": {"horizon": "15m", "value": 1.0 + change / 100},
            "percent_change_first_to_last": change, "observations": 2}}, "evidence_only": True}


def test_repeated_structural_paths_are_grouped():
    result = discover_market_path_patterns([_analysis(20), _analysis(20), _analysis(-10)])
    assert result["status"] == "OBSERVED"
    assert result["observed_market_count"] == 3
    assert result["patterns"][0]["occurrence_count"] == 2
    assert result["patterns"][0]["evidence_only"] is True


def test_missing_observations_remain_unknown():
    result = discover_market_path_patterns([{"status": "UNKNOWN"}])
    assert result["status"] == "UNKNOWN"
    assert result["patterns"] == []
    assert result["missing"] == ["market_lifecycle_analysis"]


def test_patterns_have_no_predictive_fields():
    pattern = discover_market_path_patterns([_analysis(50), _analysis(50)])["patterns"][0]
    assert all(key not in pattern for key in ("probability", "risk", "quality", "prediction", "trade_signal"))
