from datetime import datetime, timedelta, timezone

from stinky_core.depth import (
    DepthQuoteObservation,
    latest_depth_observation,
    latest_usable_depth_observation,
)


def _good(at, *, mint="mint-a", amount=10_000_000, impact=0.01):
    return DepthQuoteObservation(
        mint, at, amount, 123, impact, True, "VERIFIED",
        quote_context_slot=350000001, quote_time_taken_sec=0.01,
    )


def _bad(at, error, *, mint="mint-a", amount=10_000_000):
    return DepthQuoteObservation(mint, at, amount, None, None, False, "UNKNOWN", error=error)


def test_newer_no_route_masks_older_good_quote():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    good = _good(t0)
    no_route = _bad(t0 + timedelta(seconds=30), "NO_ROUTE")
    rows = [good, no_route]
    assert latest_depth_observation(rows, mint="mint-a", input_lamports=10_000_000, as_of=t0 + timedelta(seconds=31)) is no_route
    assert latest_usable_depth_observation(rows, mint="mint-a", input_lamports=10_000_000, as_of=t0 + timedelta(seconds=31)) is None


def test_newer_provider_failure_masks_older_good_quote():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    good = _good(t0)
    failure = _bad(t0 + timedelta(seconds=20), "HTTP_429")
    assert latest_usable_depth_observation(
        [failure, good], mint="mint-a", input_lamports=10_000_000, as_of=t0 + timedelta(seconds=21)
    ) is None


def test_conflicting_newer_verified_quote_is_not_hidden_by_older_quote():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    older = _good(t0, impact=0.01)
    newer = _good(t0 + timedelta(seconds=10), impact=0.25)
    selected = latest_usable_depth_observation(
        [older, newer], mint="mint-a", input_lamports=10_000_000, as_of=t0 + timedelta(seconds=11)
    )
    assert selected is newer
    assert selected.price_impact_pct == 0.25


def test_other_order_size_or_future_evidence_cannot_mask_current_identity():
    t0 = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    current = _good(t0)
    other_size = _bad(t0 + timedelta(seconds=10), "NO_ROUTE", amount=50_000_000)
    future = _bad(t0 + timedelta(minutes=5), "NO_ROUTE")
    selected = latest_usable_depth_observation(
        [current, other_size, future], mint="mint-a", input_lamports=10_000_000, as_of=t0 + timedelta(seconds=20)
    )
    assert selected is current
