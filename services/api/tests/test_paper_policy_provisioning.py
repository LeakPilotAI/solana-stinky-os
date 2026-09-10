from stinky_api.paper_policy_provisioning import validate_paper_configuration


def valid_config():
    return {
        "paper_policy": {
            "policy_version": "paper-v1",
            "horizon": "15m",
            "min_runner_probability": 0.6,
            "max_fade_probability": 0.25,
            "min_nonnegative_market_cap_probability": 0.7,
        },
        "execution_assumptions": {
            "entry_slippage_bps": 100,
            "exit_slippage_bps": 100,
            "entry_fee_bps": 50,
            "exit_fee_bps": 50,
            "latency_ms": 500,
        },
        "paper_notional_usd": 20,
    }


def test_valid_policy_is_deterministically_versioned_and_non_live():
    a = validate_paper_configuration(valid_config())
    b = validate_paper_configuration(valid_config())
    assert a["status"] == "VALIDATED"
    assert a["policy_sha256"] == b["policy_sha256"]
    assert len(a["policy_sha256"]) == 64
    assert a["live_execution"] is False
    assert a["trading_authority"] is False
    assert a["order_submitted"] is False
    assert a["wallet_mutated"] is False


def test_missing_thresholds_fail_closed_instead_of_defaulting():
    config = valid_config()
    config["paper_policy"]["min_runner_probability"] = None
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "min_runner_probability" in result["missing"]


def test_notional_above_twenty_is_rejected():
    config = valid_config()
    config["paper_notional_usd"] = 20.01
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "paper_notional_usd" in result["missing"]


def test_unknown_horizon_is_rejected():
    config = valid_config()
    config["paper_policy"]["horizon"] = "2h"
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "horizon" in result["missing"]
