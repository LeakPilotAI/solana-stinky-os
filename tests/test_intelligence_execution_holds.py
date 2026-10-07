from pathlib import Path


SRC = Path("scripts/research_intelligence_execution_holds.py")


def source():
    return SRC.read_text(encoding="utf-8")


def test_ie9b_is_retrospective_read_only_research():
    s = source()
    assert "retrospective_hypothesis_research" in s
    assert '"read_only": True' in s
    assert '"policy_retuning_permitted": False' in s
    assert '"prospective_validation": False' in s
    assert '"live_trading_authority": False' in s
    assert "INSERT INTO" not in s
    assert "UPDATE " not in s
    assert "DELETE FROM" not in s


def test_ie9b_preserves_v1_entry_contract():
    s = source()
    assert 'POLICY = "genesis-paper-execution-v1"' in s
    assert "ENTRY_LATENCY_SEC = 30" in s
    assert "COST_PCT = 0.02" in s
    assert "MIN_ENTRY_LIQUIDITY_USD = 1000.0" in s


def test_ie9b_uses_small_predeclared_hold_family():
    s = source()
    assert "HOLD_SECONDS = (60, 120, 180, 300, 600, 900)" in s


def test_ie9b_uses_first_observation_after_target_not_hindsight_peak():
    s = source()
    assert "captured_at >= $2" in s
    assert "ORDER BY captured_at" in s
    assert "LIMIT 1" in s
    assert "MAX(price_usd)" not in s
    assert "peak_multiple" not in s


def test_ie9b_keeps_historical_results_non_prospective():
    s = source()
    assert "hypothesis-generating only" in s
    assert "prospective validation" in s


def test_ie9b_reproduces_v1_entry_window_exactly():
    s = source()
    assert "async def v1_entry" in s
    assert "v1_exit_target = entry_target + timedelta(seconds=900)" in s
    assert 'row["captured_at"] <= v1_exit_target' in s


def test_ie9b_varies_only_scheduled_hold_not_entry_observation_delay():
    s = source()
    assert "exit_target = entry_target + timedelta(" in s
    assert 'exit_target = entry["captured_at"] + timedelta(' not in s
    assert "first_exit_at_or_after" in s
