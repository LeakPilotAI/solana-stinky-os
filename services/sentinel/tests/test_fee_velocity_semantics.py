from stinky_core.fees import (
    FeeStatus,
    fee_velocity_sol_per_minute,
    verified_observation,
)


def _exact(mint: str, value: float, at: str):
    obs = verified_observation(
        mint,
        value,
        protocol="pumpswap",
        source="pump.fun/total_fees_sol",
        confidence=1.0,
        scan_complete=True,
        lower_bound=False,
    )
    return type(obs)(
        **{**obs.__dict__, "fees_observed_at": at}
    )


def test_velocity_uses_only_exact_complete_prospective_totals():
    older = _exact("mint", 2.0, "2026-09-27T12:00:00+00:00")
    newer = _exact("mint", 5.0, "2026-09-27T12:02:00+00:00")
    assert fee_velocity_sol_per_minute(older, newer) == 1.5


def test_lower_bounds_are_never_subtracted_as_exact_totals():
    older = _exact("mint", 2.0, "2026-09-27T12:00:00+00:00")
    newer = _exact("mint", 5.0, "2026-09-27T12:02:00+00:00")
    older = type(older)(**{**older.__dict__, "lower_bound": True, "scan_complete": False})
    assert fee_velocity_sol_per_minute(older, newer) is None


def test_unknown_unverified_or_incomplete_is_not_velocity():
    older = _exact("mint", 2.0, "2026-09-27T12:00:00+00:00")
    newer = _exact("mint", 5.0, "2026-09-27T12:02:00+00:00")
    unverified = type(older)(**{**older.__dict__, "fees_verified": False, "fees_status": FeeStatus.UNKNOWN})
    incomplete = type(newer)(**{**newer.__dict__, "scan_complete": False})
    assert fee_velocity_sol_per_minute(unverified, newer) is None
    assert fee_velocity_sol_per_minute(older, incomplete) is None


def test_cross_mint_reverse_time_and_decreasing_totals_fail_closed():
    older = _exact("mint-a", 5.0, "2026-09-27T12:00:00+00:00")
    other = _exact("mint-b", 6.0, "2026-09-27T12:01:00+00:00")
    reverse_time = _exact("mint-a", 6.0, "2026-09-27T11:59:00+00:00")
    decreasing = _exact("mint-a", 4.0, "2026-09-27T12:01:00+00:00")
    assert fee_velocity_sol_per_minute(older, other) is None
    assert fee_velocity_sol_per_minute(older, reverse_time) is None
    assert fee_velocity_sol_per_minute(older, decreasing) is None
