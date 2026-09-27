from datetime import datetime, timedelta, timezone

from stinky_core.depth import (
    DepthQuoteObservation,
    depth_observation_is_fresh,
    depth_observation_matches_order,
)


def _obs(at):
    return DepthQuoteObservation(
        "mint-a", at, 10_000_000, 123, 0.01, True, "VERIFIED",
        quote_context_slot=350000001, quote_time_taken_sec=0.01,
    )


def test_depth_freshness_boundary_is_inclusive_and_restart_does_not_refresh_time():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    persisted = _obs(t0)
    assert depth_observation_is_fresh(persisted, as_of=t0 + timedelta(seconds=120))
    assert not depth_observation_is_fresh(persisted, as_of=t0 + timedelta(seconds=120, microseconds=1))
    # Reusing the persisted object after restart cannot make it current again.
    assert not depth_observation_is_fresh(persisted, as_of=t0 + timedelta(hours=1))


def test_future_or_naive_depth_time_fails_closed():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    assert not depth_observation_is_fresh(_obs(t0 + timedelta(seconds=1)), as_of=t0)
    assert not depth_observation_is_fresh(_obs(t0.replace(tzinfo=None)), as_of=t0)


def test_unknown_depth_never_becomes_fresh():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    obs = DepthQuoteObservation("mint-a", t0, 10_000_000, None, None, False, "UNKNOWN")
    assert not depth_observation_is_fresh(obs, as_of=t0)


def test_order_identity_must_match_exact_mint_and_probe_size():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    obs = _obs(t0)
    assert depth_observation_matches_order(obs, mint="mint-a", input_lamports=10_000_000)
    assert not depth_observation_matches_order(obs, mint="mint-b", input_lamports=10_000_000)
    assert not depth_observation_matches_order(obs, mint="mint-a", input_lamports=50_000_000)
