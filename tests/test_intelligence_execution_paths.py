from pathlib import Path

SRC = Path("scripts/analyze_intelligence_execution_paths.py")


def source():
    return SRC.read_text(encoding="utf-8")


def test_ie9a_is_read_only_and_non_authoritative():
    s = source()
    assert 'POLICY = "genesis-paper-execution-v1"' in s
    assert '"read_only": True' in s
    assert '"policy_retuning_permitted": False' in s
    assert '"live_trading_authority": False' in s
    assert "INSERT INTO" not in s
    assert "UPDATE " not in s
    assert "DELETE FROM" not in s


def test_ie9a_preserves_frozen_v1_assumptions():
    s = source()
    assert "ENTRY_LATENCY_SEC = 30" in s
    assert "HOLD_SEC = 900" in s
    assert "COST_PCT = 0.02" in s
    assert "MIN_ENTRY_LIQUIDITY_USD = 1000.0" in s


def test_ie9a_marks_hindsight_extrema_as_diagnostic_only():
    s = source()
    assert "descriptive_post_outcome_diagnostic" in s
    assert "Path extrema use hindsight" in s
    assert "max_favorable_excursion_pct" in s
    assert "max_adverse_excursion_pct" in s
    assert "time_to_peak_sec" in s
    assert "time_to_trough_sec" in s


def test_ie9a_distinguishes_missing_path_from_liquidity_reject():
    s = source()
    assert '"NO_MARKET_PATH"' in s
    assert '"NO_ENTRY_OBSERVATION"' in s
    assert '"ENTRY_LIQUIDITY_REJECT"' in s
    assert '"NO_POST_ENTRY_PATH"' in s
    assert '"PATH_OBSERVED"' in s


def test_ie9a_uses_market_snapshots_and_reports_coverage():
    s = source()
    assert "FROM market_snapshots" in s
    assert "migration_snapshots" not in s
    assert "gap_stats" in s
    assert '"coverage": gap_stats(snaps)' in s


def test_ie9a_recovery_excludes_entry_snapshot_and_reports_coverage_quality():
    s = source()
    assert "post_entry[1:]" in s
    assert '"recovered_after_drawdown"' in s
    assert '"recovered_to_entry_within_hold"' not in s
    assert '"coverage_quality"' in s
    assert '"NONE"' in s
    assert '"SPARSE"' in s
    assert '"DEGRADED"' in s
    assert '"GOOD"' in s
