from datetime import datetime, timedelta, timezone

from stinky_core.memory import IntelligenceMemory
from stinky_core.quality_state import MAX_LIQUIDITY_AGE_SEC, evaluate_quality_state


def _tick(mem, at, liq):
    assert mem.record_market_tick(
        mint="mint", observed_at=at, liquidity_usd=liq,
        volume_m5_usd=40000.0, price_usd=0.01,
        pair_address="pair-a", dex_id="pumpswap",
    )


def test_stale_same_pair_liquidity_cannot_drive_quality_delta():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    latest = t0 + timedelta(seconds=60)
    _tick(mem, t0, 10000.0)
    _tick(mem, latest, 1000.0)
    as_of = latest + timedelta(seconds=MAX_LIQUIDITY_AGE_SEC + 1)
    row = evaluate_quality_state(mem, mint="mint", t0=t0, as_of=as_of)
    assert "liquidity_stale" in row["unknown"]
    assert "liquidity" not in row["known"]
    assert row["latest"]["liquidity_fresh"] is False
    assert not any("liquidity down" in w["explanation"] for w in row["why"])


def test_fresh_same_pair_liquidity_still_drives_collapse_signal():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    latest = t0 + timedelta(seconds=60)
    _tick(mem, t0, 10000.0)
    _tick(mem, latest, 1000.0)
    row = evaluate_quality_state(mem, mint="mint", t0=t0, as_of=latest)
    assert "liquidity_stale" not in row["unknown"]
    assert "liquidity" in row["known"]
    assert row["latest"]["liquidity_fresh"] is True
    assert row["state"] == "FAILED"


def test_freshness_boundary_is_inclusive():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    latest = t0 + timedelta(seconds=60)
    _tick(mem, t0, 10000.0)
    _tick(mem, latest, 9000.0)
    row = evaluate_quality_state(
        mem, mint="mint", t0=t0,
        as_of=latest + timedelta(seconds=MAX_LIQUIDITY_AGE_SEC),
    )
    assert row["latest"]["liquidity_fresh"] is True
    assert "liquidity" in row["known"]


def test_stale_tick_cannot_drive_volume_or_buy_sell_pressure():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    latest = t0 + timedelta(seconds=60)
    assert mem.record_market_tick(
        mint="mint", observed_at=t0, liquidity_usd=10000.0,
        volume_m5_usd=100000.0, price_usd=0.01,
        pair_address="pair-a", dex_id="pumpswap", buys=20, sells=1,
    )
    assert mem.record_market_tick(
        mint="mint", observed_at=latest, liquidity_usd=9000.0,
        volume_m5_usd=1000.0, price_usd=0.01,
        pair_address="pair-a", dex_id="pumpswap", buys=1, sells=20,
    )

    row = evaluate_quality_state(
        mem, mint="mint", t0=t0,
        as_of=latest + timedelta(seconds=MAX_LIQUIDITY_AGE_SEC + 1),
    )

    assert "volume_5m_stale" in row["unknown"]
    assert "buy_sell_pressure_stale" in row["unknown"]
    assert "volume_5m" not in row["known"]
    assert "buy_sell_pressure" not in row["known"]
    assert not any(w["metric"] in {"volume_m5_usd", "buy_sell_ratio"} for w in row["why"])
