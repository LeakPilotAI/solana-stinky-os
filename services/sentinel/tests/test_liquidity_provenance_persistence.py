from stinky_core.memory import (
    IntelligenceMemory,
    MEMORY_ALTERS,
    MEMORY_DDL,
    MEMORY_INSERT_MARKET_OBS,
    MEMORY_SELECT_MARKET_OBS,
)


def test_market_observation_sql_contract_persists_pair_identity():
    assert "pair_address TEXT" in MEMORY_DDL
    assert "dex_id TEXT" in MEMORY_DDL
    assert any("market_observations ADD COLUMN IF NOT EXISTS pair_address TEXT" in q for q in MEMORY_ALTERS)
    assert any("market_observations ADD COLUMN IF NOT EXISTS dex_id TEXT" in q for q in MEMORY_ALTERS)
    assert ":pair_address" in MEMORY_INSERT_MARKET_OBS
    assert ":dex_id" in MEMORY_INSERT_MARKET_OBS
    assert "pair_address" in MEMORY_SELECT_MARKET_OBS
    assert "dex_id" in MEMORY_SELECT_MARKET_OBS


def test_market_tick_snapshot_and_hydration_round_trip_pair_identity():
    before = IntelligenceMemory()
    assert before.record_market_tick(
        mint="mint",
        observed_at="2026-09-27T12:00:00+00:00",
        liquidity_usd=12345.0,
        volume_m5_usd=40000.0,
        pair_address="pair-a",
        dex_id="pumpswap",
    )
    rows = before.snapshot_rows()["market_ticks"]
    assert rows[0]["pair_address"] == "pair-a"
    assert rows[0]["dex_id"] == "pumpswap"

    after = IntelligenceMemory()
    assert after.load_market_ticks(rows) == 1
    tick = after.market_ticks[0]
    assert tick.pair_address == "pair-a"
    assert tick.dex_id == "pumpswap"
    assert tick.liquidity_usd == 12345.0


def test_resume_watch_prefers_persisted_market_identity_contract():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("async def _resume_open_watches")
    end = source.index("def _track_background_task", start)
    block = source[start:end]

    assert 'getattr(mem, "market_ticks", [])' in block
    assert 'getattr(latest_tick, "pair_address", None)' in block
    assert 'getattr(latest_tick, "dex_id", None)' in block
    assert "persisted_pair" in block
    assert "persisted_dex" in block
