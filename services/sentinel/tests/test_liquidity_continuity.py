from datetime import datetime, timedelta, timezone

from stinky_core.memory import IntelligenceMemory
from stinky_core.quality_state import evaluate_quality_state


def _tick(mem, mint, at, liq, pair, dex="pumpswap"):
    assert mem.record_market_tick(
        mint=mint, observed_at=at, liquidity_usd=liq,
        volume_m5_usd=40000.0, price_usd=0.01,
        pair_address=pair, dex_id=dex,
    )


def test_pair_switch_cannot_be_interpreted_as_liquidity_improvement():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    _tick(mem, "mint", t0, 10000.0, "pair-a")
    _tick(mem, "mint", t0 + timedelta(minutes=1), 500000.0, "pair-b")
    row = evaluate_quality_state(mem, mint="mint", t0=t0, as_of=t0 + timedelta(minutes=1))
    assert "liquidity_continuity" in row["unknown"]
    assert "liquidity" not in row["known"]
    assert not any(w["metric"] == "liquidity_usd" and "up" in w["explanation"] for w in row["why"])
    assert row["gate"]["pair_address"] == "pair-a"
    assert row["latest"]["pair_address"] == "pair-b"


def test_missing_pair_identity_cannot_support_liquidity_comparison():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    _tick(mem, "mint", t0, 10000.0, None)
    _tick(mem, "mint", t0 + timedelta(minutes=1), 1000.0, None)
    row = evaluate_quality_state(mem, mint="mint", t0=t0, as_of=t0 + timedelta(minutes=1))
    assert "liquidity_continuity" in row["unknown"]
    assert "liquidity" not in row["known"]


def test_same_pair_and_dex_retains_liquidity_deterioration_signal():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    _tick(mem, "mint", t0, 10000.0, "pair-a")
    _tick(mem, "mint", t0 + timedelta(minutes=1), 1000.0, "pair-a")
    row = evaluate_quality_state(mem, mint="mint", t0=t0, as_of=t0 + timedelta(minutes=1))
    assert "liquidity" in row["known"]
    assert "liquidity_continuity" not in row["unknown"]
    assert row["state"] == "FAILED"
