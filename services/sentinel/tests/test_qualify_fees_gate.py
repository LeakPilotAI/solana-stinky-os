"""Hard fee gate tests for qualify_fresh_pump_migration (fail-closed)."""

from __future__ import annotations

from sentinel.qualify import MIN_GLOBAL_FEES_PAID_SOL, QualifyResult, qualify_fresh_pump_migration


def _q(**kw) -> QualifyResult:
    base = {
        "mint": "Abc123pump",
        "dex_id": "pumpswap",
        "global_fees_paid_sol": 6.0,
        "global_fees_verified": True,
    }
    base.update(kw)
    return qualify_fresh_pump_migration(**base)


def test_default_min_is_five():
    assert MIN_GLOBAL_FEES_PAID_SOL == 5.0


def test_fees_zero_reject():
    r = _q(global_fees_paid_sol=0.0)
    assert r.accepted is False
    assert r.reason == "LOW_GLOBAL_FEES"


def test_fees_below_five_reject():
    for fee in (0.1, 0.5, 0.99, 1.0, 3.0, 4.99):
        r = _q(global_fees_paid_sol=fee)
        assert r.accepted is False, f"fees={fee}"
        assert r.reason == "LOW_GLOBAL_FEES"


def test_fees_five_pass():
    r = _q(global_fees_paid_sol=5.0)
    assert r.accepted is True
    assert r.reason == "ok"


def test_unknown_fees_reject():
    r = _q(global_fees_paid_sol=None)
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNKNOWN"


def test_unverified_fees_reject():
    r = _q(global_fees_paid_sol=10.0, global_fees_verified=False)
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNVERIFIED"


def test_verified_none_with_number_reject():
    r = _q(global_fees_paid_sol=10.0, global_fees_verified=None)
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNVERIFIED"


def test_nan_reject():
    r = _q(global_fees_paid_sol=float("nan"))
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNKNOWN"


def test_negative_reject():
    r = _q(global_fees_paid_sol=-1.0)
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNKNOWN"


def test_wrong_dex_reject():
    r = _q(dex_id="raydium", global_fees_paid_sol=10.0)
    assert r.accepted is False
    assert "DEX" in r.reason


def test_non_pump_mint_reject():
    r = _q(mint="SoMeMintAddress", global_fees_paid_sol=10.0)
    assert r.accepted is False
    assert r.reason == "NOT_PUMP_MINT"


def test_high_score_cannot_override():
    r = _q(global_fees_paid_sol=0.42)
    assert r.accepted is False
    assert r.reason == "LOW_GLOBAL_FEES"


def test_invariant_sub_five_never_accepted():
    for fee in (0.0, 0.01, 0.42, 0.99, 1.0, 3.0, 4.99):
        r = qualify_fresh_pump_migration(
            mint="Abc123pump",
            dex_id="pumpswap",
            global_fees_paid_sol=fee,
            global_fees_verified=True,
        )
        assert r.accepted is False
