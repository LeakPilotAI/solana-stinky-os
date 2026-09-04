"""Gate 1 admission contract."""

from __future__ import annotations

from stinky_core.admission import (
    DEFAULT_MIN_VOLUME_USD,
    GATE1_VOLUME_5M_USD,
    GATE1_VOLUME_CALIBRATION_MAX_USD,
    ReasonCode,
    clamp_gate1_volume,
    evaluate_admission,
)

MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def _base(**kw):
    d = dict(
        mint=MINT,
        protocol="pumpfun",
        volume_usd=33_000.0,
        migrated=True,
    )
    d.update(kw)
    return d


def test_gate1_volume_is_33k():
    assert DEFAULT_MIN_VOLUME_USD == GATE1_VOLUME_5M_USD == 33_000.0
    assert GATE1_VOLUME_CALIBRATION_MAX_USD == 200_000.0
    assert clamp_gate1_volume(500_000) == 200_000.0
    assert clamp_gate1_volume(None) == 33_000.0


def test_boundaries():
    assert evaluate_admission(**_base(volume_usd=32_999)).eligible is False
    assert evaluate_admission(**_base(volume_usd=33_000)).eligible is True
    assert evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None)).eligible is True
    assert evaluate_admission(**_base(protocol="raydium")).eligible is False
    assert evaluate_admission(**_base(volume_usd=32_999)).rejection_reason == ReasonCode.VOLUME_BELOW_MIN
