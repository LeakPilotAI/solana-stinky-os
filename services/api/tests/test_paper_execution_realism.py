from copy import deepcopy

import pytest

from stinky_api.paper_execution_realism import simulate_paper_execution


def decision(action="WOULD_ENTER"):
    return {
        "status": "OBSERVED",
        "shadow_action": action,
        "t0_snapshot": {"temporal_cutoff_enforced": True, "future_evidence_used": False, "x": 1},
        "trading_authority": False,
        "trade_signal": False,
        "live_execution": False,
        "paper_only": True,
    }


def assumptions():
    return {
        "entry_slippage_bps": 100,
        "exit_slippage_bps": 150,
        "entry_fee_bps": 50,
        "exit_fee_bps": 50,
        "latency_ms": 750,
    }


def test_simulates_open_fill_with_explicit_costs_only():
    result = simulate_paper_execution(decision(), assumptions(), reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "SIMULATED_OPEN"
    assert result["simulated_entry_price"] == pytest.approx(1.01)
    assert result["entry_fee_usd"] == pytest.approx(0.5)
    assert result["simulated_quantity"] == pytest.approx(99.5 / 1.01)
    assert result["order_submitted"] is False
    assert result["rpc_contacted"] is False
    assert result["live_execution"] is False


def test_closed_fill_includes_round_trip_slippage_fees_and_pnl():
    result = simulate_paper_execution(decision(), assumptions(), reference_entry_price=1.0, reference_exit_price=2.0, notional_usd=100.0)
    assert result["status"] == "SIMULATED_CLOSED"
    assert result["simulated_exit_price"] == pytest.approx(1.97)
    expected_qty = 99.5 / 1.01
    gross = expected_qty * 1.97
    net = gross * 0.995
    assert result["net_exit_usd"] == pytest.approx(net)
    assert result["net_pnl_usd"] == pytest.approx(net - 100.0)
    assert result["round_trip_costs_included"] is True


def test_would_skip_never_simulates_entry():
    result = simulate_paper_execution(decision("WOULD_SKIP"), assumptions(), reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "would_enter_shadow_action" in result["missing"]


def test_missing_assumptions_fail_closed():
    result = simulate_paper_execution(decision(), {}, reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "entry_slippage_bps" in result["missing"]
    assert "latency_ms" in result["missing"]


def test_negative_assumptions_fail_closed():
    values = assumptions()
    values["entry_slippage_bps"] = -1
    result = simulate_paper_execution(decision(), values, reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "nonnegative_entry_slippage_bps" in result["missing"]


def test_unsafe_shadow_authority_is_rejected():
    unsafe = decision()
    unsafe["trading_authority"] = True
    result = simulate_paper_execution(unsafe, assumptions(), reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "shadow_trading_authority_disabled" in result["missing"]


def test_temporally_unsafe_snapshot_is_rejected():
    unsafe = decision()
    unsafe["t0_snapshot"]["future_evidence_used"] = True
    result = simulate_paper_execution(unsafe, assumptions(), reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "t0_future_evidence_excluded" in result["missing"]


def test_nonpositive_prices_and_notional_fail_closed():
    result = simulate_paper_execution(decision(), assumptions(), reference_entry_price=0, reference_exit_price=-1, notional_usd=0)
    assert result["status"] == "UNKNOWN"
    assert "positive_reference_entry_price" in result["missing"]
    assert "positive_reference_exit_price" in result["missing"]
    assert "positive_notional_usd" in result["missing"]


def test_entry_fee_cannot_consume_entire_notional():
    values = assumptions()
    values["entry_fee_bps"] = 10_000
    result = simulate_paper_execution(decision(), values, reference_entry_price=1.0, notional_usd=100.0)
    assert result["status"] == "UNKNOWN"
    assert "positive_notional_after_entry_fee" in result["missing"]


def test_input_mutation_after_simulation_cannot_rewrite_frozen_record():
    source = decision()
    original = deepcopy(source)
    result = simulate_paper_execution(source, assumptions(), reference_entry_price=1.0, notional_usd=100.0)
    source["t0_snapshot"]["x"] = 999
    assert result["shadow_decision"] == original
    assert result["shadow_decision"]["t0_snapshot"]["x"] == 1
