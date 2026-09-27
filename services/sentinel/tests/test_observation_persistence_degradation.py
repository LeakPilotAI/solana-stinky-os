import pytest

from sentinel.volume import VolumeMonitor


class _BrokenSessionContext:
    async def __aenter__(self):
        raise RuntimeError("database unavailable")

    async def __aexit__(self, *_args):
        return False


def _broken_sessions():
    return _BrokenSessionContext()


def _monitor():
    monitor = object.__new__(VolumeMonitor)
    monitor._sessions = _broken_sessions
    monitor._observation_persistence_degraded = {}
    return monitor


@pytest.mark.asyncio
async def test_depth_persistence_failure_marks_observation_degraded():
    monitor = _monitor()
    obs = type("Obs", (), {"mint": "mint-a"})()

    await monitor._persist_depth_observation(obs)

    state = monitor.observation_persistence_degraded
    assert "depth_observation" in state
    assert "database unavailable" in state["depth_observation"]


@pytest.mark.asyncio
async def test_market_snapshot_failure_marks_observation_degraded():
    monitor = _monitor()
    snap = type(
        "Snap",
        (),
        {
            "price_usd": 1.0,
            "liquidity_usd": 10_000.0,
            "volume_m5_usd": 50_000.0,
            "pair_address": "pair-a",
            "dex_id": "pumpswap",
        },
    )()

    await monitor._persist_market_snapshot("mint-a", snap)

    state = monitor.observation_persistence_degraded
    assert "market_snapshot" in state
    assert "database unavailable" in state["market_snapshot"]


def test_persistence_degradation_property_returns_copy():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "failed")

    snapshot = monitor.observation_persistence_degraded
    snapshot["depth_observation"] = "mutated"

    assert monitor.observation_persistence_degraded["depth_observation"] == "failed"
