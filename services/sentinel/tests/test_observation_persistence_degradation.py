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


class _HealthySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, *_args, **_kwargs):
        return None

    async def commit(self):
        return None


def _healthy_sessions():
    return _HealthySession()


@pytest.mark.asyncio
async def test_successful_depth_write_clears_current_degradation():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "database unavailable")
    monitor._sessions = _healthy_sessions
    obs = type(
        "Obs",
        (),
        {
            "mint": "mint-a",
            "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "input_lamports": 10_000_000,
            "out_amount_atomic": None,
            "price_impact_pct": None,
            "route_found": False,
            "status": "UNKNOWN",
            "source": "test",
            "error": "HTTP_429",
            "quote_context_slot": None,
            "quote_time_taken_sec": None,
            "expected_pair_address": "pair-a",
            "expected_dex_id": "pumpswap",
            "route_amm_keys": (),
        },
    )()

    await monitor._persist_depth_observation(obs)

    assert "depth_observation" not in monitor.observation_persistence_degraded


def test_recovery_of_one_stream_does_not_clear_other_failures():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._mark_observation_persistence_degraded("market_snapshot", "market failed")

    monitor._clear_observation_persistence_degraded("depth_observation")

    assert monitor.observation_persistence_degraded == {
        "market_snapshot": "market failed"
    }


@pytest.mark.asyncio
async def test_filter_evaluation_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._threshold = 33_000.0

    await monitor._record_filter_eval(
        mint="mint-a",
        accepted=False,
        reason="LOW_VOLUME",
        fees_sol=None,
        fees_verified=False,
    )

    state = monitor.observation_persistence_degraded
    assert "filter_evaluation" in state
    assert "database unavailable" in state["filter_evaluation"]


@pytest.mark.asyncio
async def test_successful_filter_evaluation_clears_only_its_degradation():
    monitor = _monitor()
    monitor._threshold = 33_000.0
    monitor._mark_observation_persistence_degraded("filter_evaluation", "audit failed")
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._sessions = _healthy_sessions

    await monitor._record_filter_eval(
        mint="mint-a",
        accepted=True,
        reason=None,
        fees_sol=None,
        fees_verified=False,
    )

    assert monitor.observation_persistence_degraded == {
        "depth_observation": "depth failed"
    }


def test_persistence_health_emits_only_state_transitions(capsys):
    monitor = _monitor()

    monitor._mark_observation_persistence_degraded("depth_observation", "first failure")
    monitor._mark_observation_persistence_degraded("depth_observation", "second failure")
    monitor._clear_observation_persistence_degraded("depth_observation")

    output = capsys.readouterr().out
    assert output.count("observation_persistence.degraded") == 1
    assert output.count("observation_persistence.recovered") == 1
    assert "depth_observation" in output


def _market_tick_snap():
    from datetime import datetime, timezone
    return type(
        "Snap",
        (),
        {
            "fetched_at": datetime.now(timezone.utc),
            "volume_m5_usd": 50_000.0,
            "price_usd": 1.0,
            "liquidity_usd": 10_000.0,
            "pair_address": "pair-a",
            "dex_id": "pumpswap",
            "market_cap_usd": 75_000.0,
            "txns_m5_buys": 10,
            "txns_m5_sells": 3,
        },
    )()


@pytest.mark.asyncio
async def test_market_observation_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._memory = None
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    state = monitor.observation_persistence_degraded
    assert "market_observation" in state
    assert "database unavailable" in state["market_observation"]


@pytest.mark.asyncio
async def test_successful_market_observation_clears_only_its_degradation():
    monitor = _monitor()
    monitor._memory = None
    monitor._mark_observation_persistence_degraded("market_observation", "tick failed")
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._sessions = _healthy_sessions
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    assert monitor.observation_persistence_degraded == {
        "depth_observation": "depth failed"
    }
