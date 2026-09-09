from stinky_api.walk_forward_paper_validation import evaluate_walk_forward_paper


def _policy(**overrides):
    value = {
        "minimum_closed_trades": 3,
        "minimum_mean_net_return_pct": 1.0,
        "maximum_drawdown_pct": 10.0,
        "minimum_win_rate": 0.5,
    }
    value.update(overrides)
    return value


def _row(at, ret, pnl, **overrides):
    value = {
        "status": "CLOSED",
        "mint": f"Mint-{at}",
        "closed_at": at,
        "net_return_pct": ret,
        "net_pnl": pnl,
        "paper_notional": 100.0,
        "paper_only": True,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
    }
    value.update(overrides)
    return value


def _passing_rows():
    return [
        _row("2026-09-09T13:03:00+00:00", 4.0, 4.0),
        _row("2026-09-09T13:01:00+00:00", 2.0, 2.0),
        _row("2026-09-09T13:02:00+00:00", -1.0, -1.0),
    ]


def test_passes_only_as_release_evidence_and_sorts_chronologically():
    result = evaluate_walk_forward_paper(_passing_rows(), _policy())
    assert result["status"] == "OBSERVED"
    assert result["release_gate_passed"] is True
    assert result["release_gate_result"] == "PASS"
    assert result["chronological"] is True
    assert result["evaluated_records"][0]["closed_at"].endswith("13:01:00+00:00")
    assert result["live_canary_unlocked"] is False
    assert result["live_execution"] is False
    assert result["trading_authority"] is False


def test_negative_expectancy_fails_gate_without_becoming_unknown():
    rows = [_row("2026-09-09T13:01:00+00:00", -3, -3), _row("2026-09-09T13:02:00+00:00", -2, -2), _row("2026-09-09T13:03:00+00:00", 1, 1)]
    result = evaluate_walk_forward_paper(rows, _policy())
    assert result["status"] == "OBSERVED"
    assert result["release_gate_passed"] is False
    assert result["checks"]["mean_net_return_after_costs"] is False


def test_insufficient_closed_sample_fails_closed_unknown():
    result = evaluate_walk_forward_paper(_passing_rows()[:2], _policy())
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["minimum_closed_paper_sample"]


def test_missing_policy_thresholds_fail_closed_instead_of_inventing_them():
    result = evaluate_walk_forward_paper(_passing_rows(), {})
    assert result["status"] == "UNKNOWN"
    assert "minimum_closed_trades" in result["missing"]
    assert "minimum_mean_net_return_pct" in result["missing"]


def test_invalid_policy_values_fail_closed():
    result = evaluate_walk_forward_paper(_passing_rows(), _policy(minimum_closed_trades=0, minimum_win_rate=2))
    assert result["status"] == "UNKNOWN"
    assert "valid_minimum_closed_trades" in result["missing"]
    assert "valid_minimum_win_rate" in result["missing"]


def test_any_closed_record_claiming_live_authority_invalidates_evidence():
    rows = _passing_rows()
    rows[1]["trading_authority"] = True
    result = evaluate_walk_forward_paper(rows, _policy())
    assert result["status"] == "UNKNOWN"
    assert result["unsafe_record_indexes"] == [1]


def test_any_record_that_contacted_rpc_or_signed_or_submitted_is_rejected():
    rows = _passing_rows()
    rows[0]["rpc_contacted"] = True
    result = evaluate_walk_forward_paper(rows, _policy())
    assert result["status"] == "UNKNOWN"
    assert "safe_closed_paper_execution_records" in result["missing"]


def test_open_records_are_not_counted_as_closed_evidence():
    rows = _passing_rows() + [_row("2026-09-09T13:04:00+00:00", 100, 100, status="OPEN")]
    result = evaluate_walk_forward_paper(rows, _policy())
    assert result["closed_trade_count"] == 3
    assert result["release_gate_passed"] is True


def test_drawdown_can_fail_even_when_mean_return_is_positive():
    rows = [
        _row("2026-09-09T13:01:00+00:00", 30, 30),
        _row("2026-09-09T13:02:00+00:00", -25, -25),
        _row("2026-09-09T13:03:00+00:00", 10, 10),
    ]
    result = evaluate_walk_forward_paper(rows, _policy(maximum_drawdown_pct=5, minimum_mean_net_return_pct=1, minimum_win_rate=0.5))
    assert result["mean_net_return_pct_after_costs"] > 0
    assert result["checks"]["maximum_drawdown"] is False
    assert result["release_gate_passed"] is False


def test_no_deployed_notional_fails_closed_for_drawdown_normalization():
    rows = [row | {"paper_notional": 0} for row in _passing_rows()]
    result = evaluate_walk_forward_paper(rows, _policy())
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["paper_notional_for_drawdown_normalization"]
