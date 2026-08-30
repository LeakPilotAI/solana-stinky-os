"""Core admission copy of the 1 SOL fail-closed contract."""

from __future__ import annotations

from stinky_core.admission import DEFAULT_MIN_GLOBAL_FEES_SOL, ReasonCode, evaluate_admission

MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def _base(**kw):
    d = dict(
        mint=MINT,
        protocol="pumpfun",
        global_fees_sol=2.0,
        global_fees_verified=True,
        liquidity_usd=20.0,
        volume_usd=150_000.0,
        market_cap_usd=50_000.0,
        twitter="https://x.com/abc",
        migrated=True,
    )
    d.update(kw)
    return d


def test_min_is_one():
    assert DEFAULT_MIN_GLOBAL_FEES_SOL == 1.0


def test_boundaries():
    assert evaluate_admission(**_base(global_fees_sol=0.99)).eligible is False
    assert evaluate_admission(**_base(global_fees_sol=1.00)).eligible is True
    assert evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None)).eligible is False
    assert evaluate_admission(**_base(protocol="raydium")).eligible is False
    assert evaluate_admission(**_base(volume_usd=99_999)).eligible is False
    assert evaluate_admission(**_base(volume_usd=100_000)).eligible is True
    assert evaluate_admission(**_base(global_fees_sol=0.99)).rejection_reason == ReasonCode.FEES_BELOW_MIN
