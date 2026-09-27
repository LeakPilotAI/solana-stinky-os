from datetime import datetime, timezone

from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import observation_slices


def test_observation_slice_retains_pair_and_dex_for_liquidity_provenance():
    mem = IntelligenceMemory()
    at = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    assert mem.record_market_tick(
        mint="mint",
        observed_at=at,
        liquidity_usd=12500.0,
        volume_m5_usd=40000.0,
        price_usd=0.01,
        pair_address="pair-canonical",
        dex_id="pumpswap",
        source="observed",
    )
    path = observation_slices(mem, mint="mint", t0=at, as_of=at)
    t0 = path["slices"][0]
    assert t0["liquidity"] == 12500.0
    assert t0["pair_address"] == "pair-canonical"
    assert t0["dex_id"] == "pumpswap"


def test_different_pair_liquidity_remains_identifiably_different_evidence():
    mem = IntelligenceMemory()
    t0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc)
    assert mem.record_market_tick(
        mint="mint", observed_at=t0, liquidity_usd=12000.0,
        volume_m5_usd=40000.0, pair_address="pair-a", dex_id="pumpswap",
    )
    assert mem.record_market_tick(
        mint="mint", observed_at=t1, liquidity_usd=500000.0,
        volume_m5_usd=50000.0, pair_address="pair-b", dex_id="pumpswap",
    )
    path = observation_slices(mem, mint="mint", t0=t0, as_of=t1)
    by_offset = {row["offset_sec"]: row for row in path["slices"]}
    assert by_offset[0]["pair_address"] == "pair-a"
    assert by_offset[60]["pair_address"] == "pair-b"
    assert by_offset[60]["liquidity"] == 500000.0
