from datetime import datetime, timedelta, timezone

from stinky_core.depth import (
    DepthQuoteObservation,
    latest_depth_observation,
    latest_usable_depth_observation,
)


def _obs(*, at, pair, dex, status="VERIFIED"):
    usable = status == "VERIFIED"
    return DepthQuoteObservation(
        mint="mint-a",
        observed_at=at,
        input_lamports=10_000_000,
        out_amount_atomic=2_000_000 if usable else None,
        price_impact_pct=0.01 if usable else None,
        route_found=usable,
        status=status,
        error=None if usable else "HTTP_429",
        expected_pair_address=pair,
        expected_dex_id=dex,
        route_amm_keys=(pair,) if usable else (),
    )


def test_newer_other_pair_cannot_mask_requested_market():
    now = datetime.now(timezone.utc)
    wanted = _obs(at=now - timedelta(seconds=10), pair="pair-a", dex="pumpswap")
    other = _obs(at=now - timedelta(seconds=1), pair="pair-b", dex="pumpswap", status="UNKNOWN")

    latest = latest_depth_observation(
        [wanted, other],
        mint="mint-a",
        input_lamports=10_000_000,
        as_of=now,
        expected_pair_address="pair-a",
        expected_dex_id="pumpswap",
    )
    assert latest is wanted


def test_newer_negative_same_market_masks_older_good_quote():
    now = datetime.now(timezone.utc)
    good = _obs(at=now - timedelta(seconds=10), pair="pair-a", dex="pumpswap")
    negative = _obs(at=now - timedelta(seconds=1), pair="pair-a", dex="pumpswap", status="UNKNOWN")

    latest = latest_depth_observation(
        [good, negative],
        mint="mint-a",
        input_lamports=10_000_000,
        as_of=now,
        expected_pair_address="pair-a",
        expected_dex_id="pumpswap",
    )
    assert latest is negative
    assert latest_usable_depth_observation(
        [good, negative],
        mint="mint-a",
        input_lamports=10_000_000,
        as_of=now,
        expected_pair_address="pair-a",
        expected_dex_id="pumpswap",
    ) is None


def test_dex_identity_is_part_of_market_scope():
    now = datetime.now(timezone.utc)
    wanted = _obs(at=now - timedelta(seconds=5), pair="pair-a", dex="pumpswap")
    wrong_dex = _obs(at=now - timedelta(seconds=1), pair="pair-a", dex="otherdex", status="UNKNOWN")

    latest = latest_depth_observation(
        [wanted, wrong_dex],
        mint="mint-a",
        input_lamports=10_000_000,
        as_of=now,
        expected_pair_address="pair-a",
        expected_dex_id="pumpswap",
    )
    assert latest is wanted
