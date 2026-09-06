from stinky_api.market_path_patterns import discover_market_path_patterns


def _analysis(price_change: float, horizons=None):
    horizons = horizons or ["5m", "15m"]
    return {
        "status": "OBSERVED",
        "observed_horizons": horizons,
        "observed_record_count": len(horizons),
        "metrics": {
            "price_usd": {
                "first": {"horizon": horizons[0], "value": 1.0},
                "last": {"horizon": horizons[-1], "value": 1.0 + price_change / 100.0},
                "percent_change_first_to_last": price_change,
                "observations": len(horizons),
            }
        },
        "evidence_only": True,
    }


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
    assert result["evidence_only"] is True


def test_pattern_discovery_does_not_create_quality_or_prediction_fields():
    result = discover_market_path_patterns([_analysis(50), _analysis(50)])
    pattern = result["patterns"][0]

    assert "probability" not in pattern
    assert "risk" not in pattern
    assert "quality" not in pattern
    assert "prediction" not in pattern
    assert "trade_signal" not in pattern
