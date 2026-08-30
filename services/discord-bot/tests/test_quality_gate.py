"""Discord quality gate must call the canonical engine, then intelligence."""

from __future__ import annotations

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "packages" / "stinky-core" / "src"
sys.path.insert(0, str(CORE))

from stinky_core.admission import ReasonCode, can_alert, evaluate_admission
from stinky_core.identity import AlertLedger


MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def test_missing_fees_cannot_alert_even_with_high_score_payload():
    d = evaluate_admission(
        mint=MINT,
        protocol="pumpswap",
        global_fees_sol=None,
        global_fees_verified=None,
        liquidity_usd=20_000,
        volume_usd=500_000,
        market_cap_usd=80_000,
        twitter="https://x.com/abc",
        migrated=True,
    )
    assert d.accepted is False
    ok, reason = can_alert(d, score=99, meaningful_buyers=20)
    assert ok is False
    assert reason == ReasonCode.FEES_UNKNOWN


def test_low_fees_high_volume_rejected():
    d = evaluate_admission(
        mint=MINT,
        protocol="pumpswap",
        global_fees_sol=0.3,
        global_fees_verified=True,
        liquidity_usd=20_000,
        volume_usd=500_000,
        market_cap_usd=80_000,
        twitter="https://x.com/abc",
        migrated=True,
    )
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN
    assert can_alert(d, score=94, meaningful_buyers=12)[0] is False


def test_duplicate_discord_delivery_blocked():
    ledger = AlertLedger()
    assert ledger.try_record(MINT)[0] is True
    assert ledger.try_record(MINT)[0] is False
    assert ledger.delivered == 1
