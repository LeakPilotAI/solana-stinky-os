import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import sentinel.volume as volume
from sentinel.volume import VolumeMonitor, VolumeSnapshot


MINT = "prospective-fee-series-pump"


def _monitor():
    monitor = object.__new__(VolumeMonitor)
    monitor._memory = None
    monitor._sessions = None
    monitor._last_fee_sample_monotonic = {}
    monitor._persist_fee_observation = AsyncMock()
    return monitor


def _snapshot():
    return VolumeSnapshot(
        mint=MINT,
        pair_address="pool-1",
        dex_id="pumpswap",
        price_usd=1.0,
        liquidity_usd=25000.0,
        volume_m5_usd=100000.0,
        volume_h1_usd=None,
        txns_m5_buys=10,
        txns_m5_sells=2,
        fetched_at=datetime.now(timezone.utc),
    )


def _migration():
    return type("Migration", (), {"mint": MINT})()


def test_followup_fee_sampling_is_fresh_rate_limited_and_persists_unknown(monkeypatch):
    monitor = _monitor()
    observed = object()
    resolve = AsyncMock(return_value=observed)
    monkeypatch.setattr(volume, "resolve_global_fees", resolve)
    monkeypatch.setattr(volume.settings, "fee_observation_interval_sec", 60.0, raising=False)

    times = iter([100.0, 120.0, 161.0])
    monkeypatch.setattr(volume.time, "monotonic", lambda: next(times))

    async def run():
        await monitor._record_followup_tick(_migration(), _snapshot())
        await monitor._record_followup_tick(_migration(), _snapshot())
        await monitor._record_followup_tick(_migration(), _snapshot())

    asyncio.run(run())

    assert resolve.await_count == 2
    for call in resolve.await_args_list:
        assert call.kwargs["use_cache"] is False
        assert call.kwargs["protocol"] == "pumpswap"
        assert call.kwargs["pool"] == "pool-1"
    assert monitor._persist_fee_observation.await_count == 2
    # The collector persists the observation object without requiring VERIFIED;
    # UNKNOWN/lower-bound evidence must remain available to prospective research.
    assert monitor._persist_fee_observation.await_args_list[0].args == (observed,)


def test_followup_fee_sampling_reserves_slot_before_lookup_failure(monkeypatch):
    monitor = _monitor()
    resolve = AsyncMock(side_effect=RuntimeError("synthetic provider failure"))
    monkeypatch.setattr(volume, "resolve_global_fees", resolve)
    monkeypatch.setattr(volume.settings, "fee_observation_interval_sec", 60.0, raising=False)

    times = iter([100.0, 101.0])
    monkeypatch.setattr(volume.time, "monotonic", lambda: next(times))

    async def run():
        await monitor._record_followup_tick(_migration(), _snapshot())
        await monitor._record_followup_tick(_migration(), _snapshot())

    asyncio.run(run())

    assert resolve.await_count == 1
    assert monitor._persist_fee_observation.await_count == 0
