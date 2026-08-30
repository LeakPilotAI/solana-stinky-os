"""Hard fee gate tests for qualify_fresh_pump_migration (fail-closed)."""

from __future__ import annotations

from sentinel.qualify import MIN_GLOBAL_FEES_PAID_SOL, QualifyResult, qualify_fresh_pump_migration
from stinky_core.admission import ReasonCode


def _q(**kw) -> QualifyResult:
    base = {
        "mint": "Abc1234567890Abc1234567890Abc123pump",
        "dex_id": "pumpswap",
        "global_fees_paid_sol": 6.0,
        "global_fees_verified": True,
    }
    base.update(kw)
    return qualify_fresh_pump_migration(**base)


def test_default_min_is_one():
    assert MIN_GLOBAL_FEES_PAID_SOL == 1.0


def test_fees_zero_reject():
    r = _q(global_fees_paid_sol=0.0)
    assert r.accepted is False
    assert r.reason == ReasonCode.FEES_BELOW_MIN


def test_fees_below_one_reject():
    for fee in (0.1, 0.3, 0.5, 0.99):
        r = _q(global_fees_paid_sol=fee)
        assert r.accepted is False, f"fees={fee}"
        assert r.reason == ReasonCode.FEES_BELOW_MIN


def test_fees_one_pass():
    r = _q(global_fees_paid_sol=1.0)
    assert r.accepted is True
    assert r.reason == "ok"


def test_unknown_fees_reject():
    r = _q(global_fees_paid_sol=None)
    assert r.accepted is False
    assert r.reason == ReasonCode.FEES_UNKNOWN


def test_unverified_fees_reject():
    r = _q(global_fees_paid_sol=10.0, global_fees_verified=False)
    assert r.accepted is False
    assert r.reason == ReasonCode.FEES_UNKNOWN


def test_verified_none_with_number_reject():
    r = _q(global_fees_paid_sol=10.0, global_fees_verified=None)
    assert r.accepted is False
    assert r.reason == ReasonCode.FEES_UNKNOWN


def test_nan_reject():
    r = _q(global_fees_paid_sol=float("nan"))
    assert r.accepted is False
    assert r.reason in (ReasonCode.FEES_UNKNOWN, ReasonCode.INVALID_MARKET_DATA)


def test_negative_reject():
    r = _q(global_fees_paid_sol=-1.0)
    assert r.accepted is False
    assert r.reason in (ReasonCode.FEES_UNKNOWN, ReasonCode.INVALID_MARKET_DATA)


def test_wrong_dex_reject():
    r = _q(dex_id="raydium", global_fees_paid_sol=10.0)
    assert r.accepted is False
    assert r.reason == ReasonCode.PROTOCOL_DISABLED


def test_non_pump_mint_reject():
    r = _q(mint="SoMeMintAddressSoMeMintAddress111111", global_fees_paid_sol=10.0)
    assert r.accepted is False
