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


import importlib.util
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest


def diagnostic_module():
    spec = importlib.util.spec_from_file_location("execution_paths_behavior", SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("age,has_exit,expected", [(929, True, "PENDING"), (930, True, "PATH_OBSERVED"), (1000, False, "PENDING")])
async def test_window_maturity_excludes_partial_extrema(monkeypatch, age, has_exit, expected):
    module = diagnostic_module()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return start + timedelta(seconds=age)
    monkeypatch.setattr(module, "datetime", Clock, raising=False)
    def snap(seconds, price):
        return {"captured_at": start + timedelta(seconds=seconds), "price_usd": price,
                "liquidity_usd": 2000, "volume_m5_usd": 100, "market_cap_usd": 1000}
    snaps = [snap(30, 10), snap(60, 5), snap(90, 20)]
    if has_exit:
        snaps.append(snap(930, 10))
    conn = AsyncMock()
    conn.fetch.side_effect = [[{"plan_id": 1, "mint": "fixture", "decided_at": start}], snaps]
    conn.fetchrow.return_value = None
    monkeypatch.setattr(module.asyncpg, "connect", AsyncMock(return_value=conn))
    report = await module.run()
    row = report["results"][0]
    assert row["status"] == expected
    assert row["window_complete"] is (expected == "PATH_OBSERVED")
    if expected == "PENDING":
        assert not any(k in row for k in ("peak_multiple", "trough_multiple", "max_favorable_excursion_pct",
            "max_adverse_excursion_pct", "time_to_peak_sec", "time_to_trough_sec", "recovered_after_drawdown",
            "peak_liquidity_usd", "trough_liquidity_usd", "net_multiple"))
        assert report["summary"]["path_observed"] == 0
        for key in ("peak_multiple", "trough_multiple", "time_to_peak_sec", "time_to_trough_sec", "fixed_exit_net_multiple"):
            assert report["summary"][key] == {"n": 0}
        assert report["summary"]["drawdown_recovery"] == {"experienced_drawdown": 0, "recovered_after_drawdown": 0}
        if age < 930:
            assert conn.fetch.await_count == 1
            conn.fetchrow.assert_not_awaited()
    else:
        assert row["peak_multiple"] == 2
        assert row["trough_multiple"] == 0.5
        assert row["recovered_after_drawdown"] is True
        assert row["net_multiple"] == 0.98
        assert report["summary"]["peak_multiple"]["n"] == 1
    assert report["read_only"] and not report["live_trading_authority"]
    conn.execute.assert_not_awaited()
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_mixed_cohort_aggregates_only_completed_windows(monkeypatch):
    module = diagnostic_module()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return now
    monkeypatch.setattr(module, "datetime", Clock)
    mature = now - timedelta(seconds=1000)
    rows = [{"plan_id": 1, "mint": "mature", "decided_at": mature},
            {"plan_id": 2, "mint": "immature", "decided_at": now - timedelta(seconds=100)}]
    def snap(sec, price):
        return {"captured_at": mature + timedelta(seconds=sec), "price_usd": price, "liquidity_usd": 2000}
    conn = AsyncMock()
    async def fetch(sql, *args):
        if sql == module.ROWS: return rows
        assert args[0] == "mature", "immature evidence must not be read"
        return [snap(30, 10), snap(60, 20), snap(930, 5)]
    conn.fetch.side_effect = fetch
    monkeypatch.setattr(module.asyncpg, "connect", AsyncMock(return_value=conn))
    report = await module.run()
    assert report["counts"] == {"PATH_OBSERVED": 1, "PENDING": 1}
    assert report["summary"]["peak_multiple"]["n"] == 1
    assert report["summary"]["peak_multiple"]["mean"] == 2
    assert report["summary"]["fixed_exit_net_multiple"]["mean"] == 0.49
    assert report["summary"]["drawdown_recovery"] == {"experienced_drawdown": 1, "recovered_after_drawdown": 0}
