import asyncio
from types import SimpleNamespace

import pytest

import sentinel.volume as volume
from sentinel.volume import VolumeMonitor


@pytest.mark.asyncio
async def test_market_snapshot_is_recorded_before_fee_provider_io(monkeypatch):
    monitor = object.__new__(VolumeMonitor)
    monitor._last_fee_sample_monotonic = {}
    monitor._sessions = None

    order = []
    depth_release = asyncio.Event()

    async def depth(_mint, **_kwargs):
        await depth_release.wait()

    async def record_market(_migration, _snap):
        order.append("market")

    async def fees(*_args, **_kwargs):
        order.append("fees")
        return SimpleNamespace()

    async def persist_fee(_obs):
        order.append("fee-persist")

    monitor._sample_depth_observation = depth
    monitor._record_market_snapshot = record_market
    monitor._persist_fee_observation = persist_fee
    monkeypatch.setattr(volume, "resolve_global_fees", fees)

    migration = SimpleNamespace(mint="mint-a")
    snap = SimpleNamespace(dex_id="pumpswap", pair_address="pair-a")

    await monitor._record_followup_tick(migration, snap)
    depth_release.set()
    await asyncio.sleep(0)

    assert order == ["market", "fees", "fee-persist"]


@pytest.mark.asyncio
async def test_slow_fee_provider_cannot_delay_market_snapshot(monkeypatch):
    monitor = object.__new__(VolumeMonitor)
    monitor._last_fee_sample_monotonic = {}
    monitor._sessions = None

    market_recorded = asyncio.Event()
    fee_started = asyncio.Event()
    fee_release = asyncio.Event()
    depth_release = asyncio.Event()

    async def depth(_mint, **_kwargs):
        await depth_release.wait()

    async def record_market(_migration, _snap):
        market_recorded.set()

    async def slow_fees(*_args, **_kwargs):
        fee_started.set()
        await fee_release.wait()
        return SimpleNamespace()

    async def persist_fee(_obs):
        return None

    monitor._sample_depth_observation = depth
    monitor._record_market_snapshot = record_market
    monitor._persist_fee_observation = persist_fee
    monkeypatch.setattr(volume, "resolve_global_fees", slow_fees)

    migration = SimpleNamespace(mint="mint-a")
    snap = SimpleNamespace(dex_id="pumpswap", pair_address="pair-a")

    task = asyncio.create_task(monitor._record_followup_tick(migration, snap))
    await asyncio.wait_for(market_recorded.wait(), timeout=0.2)
    await asyncio.wait_for(fee_started.wait(), timeout=0.2)
    assert not task.done()

    fee_release.set()
    depth_release.set()
    await asyncio.wait_for(task, timeout=0.2)
    await asyncio.sleep(0)
