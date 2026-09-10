from copy import deepcopy

from stinky_api.paper_execution_realism import simulate_paper_execution
from stinky_api.paper_walk_forward_adapter import adapt_simulated_execution_for_walk_forward
from stinky_api.walk_forward_paper_validation import evaluate_walk_forward_paper


def decision():
    return {
        "status": "OBSERVED",
        "shadow_action": "WOULD_ENTER",
        "t0_snapshot": {"temporal_cutoff_enforced": True, "future_evidence_used": False},
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


def policy():
    return {
        "minimum_closed_trades": 2,
        "minimum_mean_net_return_pct": -100.0,
        "maximum_drawdown_pct": 100.0,
        "minimum_win_rate": 0.0,
    }


def closed_sim(exit_price: float):
    return simulate_paper_execution(
        decision(),
        assumptions(),
        reference_entry_price=1.0,
        reference_exit_price=exit_price,
        notional_usd=100.0,
    )


def test_actual_159_output_adapts_directly_into_160_and_evaluates_chronologically():
    first = closed_sim(1.5)
    second = closed_sim(0.8)
    assert first["status"] == "SIMULATED_CLOSED"
    assert "net_pnl_usd" in first and "net_pnl" not in first

    rows = [
        adapt_simulated_execution_for_walk_forward(first, closed_at="2026-09-10T01:00:00+00:00", mint="mint-a"),
        adapt_simulated_execution_for_walk_forward(second, closed_at="2026-09-10T02:00:00+00:00", mint="mint-b"),
    ]
    assert all(row["status"] == "CLOSED" for row in rows)
    assert rows[0]["net_pnl"] == first["net_pnl_usd"]
    assert rows[0]["paper_notional"] == first["notional_usd"]

    result = evaluate_walk_forward_paper(rows, policy())
    assert result["status"] == "OBSERVED"
    assert result["closed_trade_count"] == 2
    assert result["chronological"] is True
    assert [row["mint"] for row in result["evaluated_records"]] == ["mint-a", "mint-b"]
    assert result["live_execution"] is False
    assert result["live_canary_unlocked"] is False


def test_adapter_requires_real_caller_supplied_close_time_instead_of_inventing_one():
    result = adapt_simulated_execution_for_walk_forward(closed_sim(1.2), closed_at="")
    assert result["status"] == "UNKNOWN"
    assert "caller_supplied_closed_at" in result["missing"]
    assert result["adapted_for_walk_forward"] is False


def test_open_159_execution_cannot_enter_walk_forward_sample():
    opened = simulate_paper_execution(
        decision(), assumptions(), reference_entry_price=1.0, notional_usd=100.0
    )
    result = adapt_simulated_execution_for_walk_forward(
        opened, closed_at="2026-09-10T01:00:00+00:00"
    )
    assert result["status"] == "UNKNOWN"
    assert "simulated_closed_execution" in result["missing"]


def test_adapter_rejects_authority_contamination_and_preserves_non_execution_boundary():
    source = closed_sim(1.2)
    source["rpc_contacted"] = True
    result = adapt_simulated_execution_for_walk_forward(
        source, closed_at="2026-09-10T01:00:00+00:00"
    )
    assert result["status"] == "UNKNOWN"
    assert "non_executing_paper_record" in result["missing"]
    assert result["live_execution"] is False


def test_adapter_requires_round_trip_costs_before_release_evidence():
    source = closed_sim(1.2)
    source["round_trip_costs_included"] = False
    result = adapt_simulated_execution_for_walk_forward(
        source, closed_at="2026-09-10T01:00:00+00:00"
    )
    assert result["status"] == "UNKNOWN"
    assert "round_trip_costs_included" in result["missing"]


def test_adapter_deep_copies_159_source_evidence():
    source = closed_sim(1.2)
    adapted = adapt_simulated_execution_for_walk_forward(
        source, closed_at="2026-09-10T01:00:00+00:00"
    )
    frozen = deepcopy(adapted["source_execution"])
    source["net_pnl_usd"] = 999999.0
    assert adapted["source_execution"] == frozen
