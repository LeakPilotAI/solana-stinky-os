"""End-to-end Genesis pipeline. SIMULATION — not live market data.

Proves: Gate 1 → one investigation → ticks including below-gate volume
→ quality → dips → Discord policy → sqlite restart → future isolation.
Does not lower Gate 1. Does not invent a live $150k print.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1
from stinky_core.intelligence import INTEL_VERSION, investigate
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import (
    investigation_record,
    observation_slices,
    slice_analogues,
    watch_should_resume,
    watch_tick_decision,
    what_happened_next,
)
from stinky_core.quality_state import FAILED, evaluate_quality_state, quality_dip
from stinky_core.sqlstore import SqliteMemoryStore

MINT = "LivePipeAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_gate1_still_150k():
    assert GATE1_VOLUME_5M_USD == 150_000
    assert INTEL_VERSION.startswith("intel-v1.10")
    d = evaluate_gate1({"mint": MINT, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True
    d = evaluate_gate1({"mint": MINT, "protocol": "pumpswap", "volume_usd": 149_999, "migrated": True})
    assert d.eligible is False


def test_watch_tick_keeps_recording_after_volume_dump():
    assert watch_tick_decision(investigated=False, gate_ok=False, reason="VOLUME_BELOW_MIN") == "wait"
    assert watch_tick_decision(investigated=False, gate_ok=True, reason="ok") == "investigate"
    assert watch_tick_decision(investigated=True, gate_ok=False, reason="VOLUME_BELOW_MIN") == "tick"
    assert watch_tick_decision(investigated=True, gate_ok=False, reason="NOT_MIGRATED") == "tick"
    assert watch_tick_decision(investigated=False, gate_ok=False, reason="PROTOCOL_DISABLED") == "stop"
    assert watch_tick_decision(investigated=False, gate_ok=False, reason="NOT_MIGRATED") == "wait"
    assert watch_should_resume(elapsed_sec=400, max_watch_sec=1800) is True
    assert watch_should_resume(elapsed_sec=1800, max_watch_sec=1800) is False
    assert watch_should_resume(elapsed_sec=-1, max_watch_sec=1800) is False


def test_simulation_full_pipeline_sqlite_restart():
    """SIMULATION. One mint at $172k Gate 1, then liquidity collapse."""
    mem = IntelligenceMemory()
    gate = evaluate_gate1(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "migrated": True, "liquidity_usd": 50_000}
    )
    assert gate.eligible is True
    rec = investigation_record(
        {
            "mint": MINT,
            "protocol": "pumpswap",
            "volume_usd": 172_000,
            "liquidity_usd": 50_000,
            "decision_timestamp": T0.isoformat(),
        },
        gate1_passed=True,
        investigation_status="INVESTIGATING",
    )
    assert mem.record_investigation(rec) is True
    assert mem.record_investigation(dict(rec, volume_5m_at_gate=999_999)) is False
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=172_000, liquidity_usd=50_000, price_usd=1.0)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=15), volume_m5_usd=168_000, liquidity_usd=49_000, price_usd=0.98
    )
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=40_000, liquidity_usd=28_000, price_usd=0.4
    )
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=8_000, liquidity_usd=4_000, price_usd=0.05
    )
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=900), volume_m5_usd=5_000, liquidity_usd=3_500, price_usd=0.04
    )
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=1800), volume_m5_usd=4_000, liquidity_usd=3_200, price_usd=0.03
    )

    t15 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=15))
    assert t15["is_dip"] is False
    assert t15["state"] != FAILED

    t60 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=60), previous_state=t15["state"])
    assert t60["is_dip"] is True
    assert quality_dip(t60) is not None

    t300 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=300), previous_state=t60["state"])
    assert t300["state"] == FAILED
    assert t300["calibrated_probability"] is False

    leaked = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=15))
    assert leaked["state"] != FAILED

    path = observation_slices(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=15))
    by = {s["offset_sec"]: s for s in path["slices"]}
    assert by[15]["volume_5m"] == 168_000
    assert by[300]["volume_5m"] != 8_000
    assert by[1800]["volume_5m"] != 4_000

    happened = what_happened_next(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=15))
    assert happened["peak_volume"] == 168_000
    assert happened["peak_volume"] != 8_000

    inv = investigate(
        {"mint": MINT, "volume_m5_usd": 172_000, "liquidity_usd": 50_000, "decision_timestamp": T0.isoformat()},
        memory=mem,
    )
    assert inv.has_intelligence is False
    assert inv.promote is False
    assert inv.score.calibrated_probability is False

    store = SqliteMemoryStore(":memory:")
    store.persist(mem)
    mem2 = store.load()
    assert any(r.get("mint") == MINT for r in mem2.investigations)
    assert len([t for t in mem2.market_ticks if t.mint == MINT]) == 6
    again = evaluate_quality_state(mem2, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=300))
    assert again["state"] == FAILED

    ana = slice_analogues(mem2, mint=MINT, offset_sec=15, t0=T0)
    assert ana["sample_sufficient"] is False
    assert ana["calibrated_probability"] is False


def test_price_down_alone_is_not_a_dip():
    mem = IntelligenceMemory()
    mem.record_investigation(
        investigation_record(
            {"mint": MINT, "protocol": "pumpswap", "volume_usd": 180_000, "liquidity_usd": 40_000,
             "decision_timestamp": T0.isoformat()},
            gate1_passed=True,
        )
    )
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=40_000, price_usd=1.0)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=120), volume_m5_usd=175_000, liquidity_usd=39_000, price_usd=0.7
    )
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=120))
    assert st["is_dip"] is False


def test_unknown_buyers_stay_unknown_in_investigation():
    inv = investigate({"mint": MINT, "volume_m5_usd": 180_000, "liquidity_usd": 40_000})
    assert inv.has_intelligence is False
    assert inv.promote is False
    assert inv.score.calibrated_probability is False
