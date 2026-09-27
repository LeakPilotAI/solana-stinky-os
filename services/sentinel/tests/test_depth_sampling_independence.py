import asyncio
from types import SimpleNamespace

import pytest

from sentinel.volume import VolumeMonitor


@pytest.mark.asyncio
async def test_followup_tick_does_not_wait_for_depth_provider(monkeypatch):
    monitor = object.__new__(VolumeMonitor)
    monitor._last_fee_sample_monotonic = {"mint-a": float("inf")}
    monitor._memory = None
    monitor._sessions = None

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_depth(mint):
        started.set()
        await release.wait()

    monitor._sample_depth_observation = slow_depth

    migration = SimpleNamespace(mint="mint-a")
    snap = SimpleNamespace(
        fetched_at=None,
        txns_m5_buys=None,
        txns_m5_sells=None,
        volume_m5_usd=1.0,
        price_usd=None,
        liquidity_usd=1.0,
        pair_address="pair",
        dex_id="pumpfun",
        market_cap_usd=None,
    )

    await asyncio.wait_for(monitor._record_followup_tick(migration, snap), timeout=0.2)
    await asyncio.wait_for(started.wait(), timeout=0.2)
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_background_depth_failure_is_consumed(capsys):
    async def fail():
        raise RuntimeError("provider down")

    task = asyncio.create_task(fail())
    await asyncio.sleep(0)
    VolumeMonitor._depth_sample_done(task)
    captured = capsys.readouterr()
    assert "depth_observation.background_failed" in captured.out
    assert "provider down" in captured.out
