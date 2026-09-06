from stinky_api.market_outcome_analysis import analyze_market_lifecycle


def test_analysis_describes_observed_path_and_extremes_only():
    records = [
        {"horizon": "5m", "metrics": {"price_usd": 1.0, "liquidity_usd": 1000}},
        {"horizon": "15m", "metrics": {"price_usd": 1.5, "liquidity_usd": 900}},
        {"horizon": "1h", "metrics": {"price_usd": 0.5, "liquidity_usd": 1200}},
    ]

    result = analyze_market_lifecycle(records)

    assert result["status"] == "OBSERVED"
    assert result["observed_horizons"] == ["5m", "15m", "1h"]
    assert result["observed_record_count"] == 3
    assert result["metrics"]["price_usd"]["first"] == {"horizon": "5m", "value": 1.0}
    assert result["metrics"]["price_usd"]["last"] == {"horizon": "1h", "value": 0.5}
    assert result["metrics"]["price_usd"]["max"] == {"horizon": "15m", "value": 1.5}
    assert result["metrics"]["price_usd"]["min"] == {"horizon": "1h", "value": 0.5}
    assert result["metrics"]["price_usd"]["percent_change_first_to_last"] == -50.0
    assert result["metrics"]["liquidity_usd"]["max"] == {"horizon": "1h", "value": 1200.0}
    assert result["evidence_only"] is True
    assert "prediction" not in result
    assert "probability" not in result


def test_analysis_does_not_invent_missing_horizons():
    result = analyze_market_lifecycle([
        {"horizon": "5m", "metrics": {"price_usd": 2.0}},
        {"horizon": "1h", "metrics": {"price_usd": 3.0}},
    ])

    assert result["observed_horizons"] == ["5m", "1h"]
    assert "15m" not in result["observed_horizons"]


def test_analysis_returns_unknown_without_records():
    result = analyze_market_lifecycle([])

    assert result["status"] == "UNKNOWN"
    assert result["metrics"] == {}
    assert result["missing"] == ["market_outcome_observations"]
    assert result["evidence_only"] is True
