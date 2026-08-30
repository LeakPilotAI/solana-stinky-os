"""Discord quality gate: Gate 1 then intelligence. Fees are not an admission reject."""

from __future__ import annotations

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "packages" / "stinky-core" / "src"
sys.path.insert(0, str(CORE))

from stinky_core.admission import ReasonCode, can_alert, evaluate_admission
from stinky_core.identity import AlertLedger


MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def test_unknown_fees_pass_gate1_but_cannot_alert_without_inspection():
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
    assert d.accepted is True
    ok, reason = can_alert(d, score=99, meaningful_buyers=20, inspection_complete=False)
    assert ok is False
    assert reason == ReasonCode.INSPECTION_INCOMPLETE


def test_low_verified_fees_do_not_block_gate1():
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
    assert d.accepted is True
    assert d.metrics.get("fee_signal") == "negative"
    assert can_alert(d, score=94, meaningful_buyers=12, inspection_complete=False)[0] is False


def test_duplicate_discord_delivery_blocked():
    ledger = AlertLedger()
    assert ledger.try_record(MINT)[0] is True
    assert ledger.try_record(MINT)[0] is False
    assert ledger.delivered == 1
