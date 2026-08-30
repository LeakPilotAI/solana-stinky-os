"""Gate 1 qualify_fresh_pump_migration (volume-first)."""

from __future__ import annotations

from sentinel.qualify import GATE1_VOLUME_5M_USD, QualifyResult, qualify_fresh_pump_migration
from stinky_core.admission import ReasonCode


def _q(**kw) -> QualifyResult:
    base = {
        "mint": "Abc1234567890Abc1234567890Abc123pump",
        "dex_id": "pumpswap",
        "volume_m5_usd": 150_000.0,
        "global_fees_paid_sol": None,
        "global_fees_verified": None,
    }
    base.update(kw)
    return qualify_fresh_pump_migration(**base)


def test_default_volume_is_150k():
    assert GATE1_VOLUME_5M_USD == 150_000.0


def test_volume_below_reject():
    r = _q(volume_m5_usd=149_999)
    assert r.accepted is False
    assert r.reason == ReasonCode.VOLUME_BELOW_MIN


def test_volume_150k_pass():
    r = _q(volume_m5_usd=150_000)
    assert r.accepted is True
    assert r.reason == "ok"


def test_unknown_fees_do_not_block():
    r = _q(global_fees_paid_sol=None, global_fees_verified=None)
    assert r.accepted is True


def test_low_verified_fees_do_not_block():
    r = _q(global_fees_paid_sol=0.2, global_fees_verified=True)
    assert r.accepted is True


def test_wrong_dex_reject():
    r = _q(dex_id="raydium")
    assert r.accepted is False
    assert r.reason == ReasonCode.PROTOCOL_DISABLED


def test_non_pump_mint_reject():
    r = _q(mint="SoMeMintAddressSoMeMintAddress111111")
    assert r.accepted is False


def test_config_above_200k_clamped():
    r = _q(volume_m5_usd=180_000, min_volume_usd=500_000)
    assert r.required == 200_000.0
    assert r.accepted is False
    assert r.reason == ReasonCode.VOLUME_BELOW_MIN
    r2 = _q(volume_m5_usd=210_000, min_volume_usd=500_000)
    assert r2.required == 200_000.0
    assert r2.accepted is True


def test_pumpfun_bonding_is_not_migrated():
    from sentinel.qualify import is_post_migration_dex

    assert is_post_migration_dex("pumpswap") is True
    assert is_post_migration_dex("pumpfun") is False
    r = _q(dex_id="pumpfun", volume_m5_usd=180_000)
    assert r.accepted is False
    assert r.reason == ReasonCode.NOT_MIGRATED


def test_watch_tick_decision_imported():
    from stinky_core.observation import watch_should_resume, watch_tick_decision

    assert watch_tick_decision(investigated=True, gate_ok=False, reason="VOLUME_BELOW_MIN") == "tick"
    assert watch_should_resume(elapsed_sec=0, max_watch_sec=1800) is True
    assert watch_should_resume(elapsed_sec=1800, max_watch_sec=1800) is False
