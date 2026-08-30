"""Quality state, dips, RUG outcome, Discord policy, T+900, contamination-safe Gate 1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import OBSERVATION_SLICES_SEC, slice_analogues
from stinky_core.outcomes import RUG, RUNNER, FADE, UNKNOWN, label_outcome
from stinky_core.quality_state import (
    FAILED,
    HEALTHY,
    SEVERE_DETERIORATION,
    UNKNOWN as QUNKNOWN,
    WATCH,
    evaluate_quality_state,
    quality_dip,
)
from stinky_core.book import LIFE_SLICES_SEC

MINT = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_gate1_unchanged():
    assert GATE1_VOLUME_5M_USD == 150_000
    d = evaluate_gate1({"mint": MINT, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True


def test_slices_include_t900():
    assert 900 in OBSERVATION_SLICES_SEC
    assert 900 in LIFE_SLICES_SEC
    assert 15 in LIFE_SLICES_SEC
    assert 1800 in LIFE_SLICES_SEC


def test_t0_only_is_unknown():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=40_000)
    st = evaluate_quality_state(mem, mint=MINT, t0=T0)
    assert st["state"] == QUNKNOWN
    assert st["is_dip"] is False
    assert quality_dip(st) is None


def test_stable_path_is_healthy_not_dip():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=40_000)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=120), volume_m5_usd=175_000, liquidity_usd=39_000
    )
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=120))
    assert st["state"] in (HEALTHY, "STABLE", "IMPROVING")
    assert st["is_dip"] is False


def test_noise_band_ignored():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=200_000, liquidity_usd=50_000)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=190_000, liquidity_usd=46_000
    )
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=60))
    assert st["state"] not in (WATCH, SEVERE_DETERIORATION, FAILED)


def test_liquidity_watch_and_failed():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=50_000)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=160_000, liquidity_usd=28_000
    )
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=300))
    assert st["state"] == WATCH
    assert st["is_dip"] is True
    assert quality_dip(st) is not None

    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=600), volume_m5_usd=20_000, liquidity_usd=4_000
    )
    st2 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=600), previous_state=WATCH)
    assert st2["state"] == FAILED
    assert st2["severity"] == "CRITICAL"


def test_future_ticks_hidden_from_quality():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=50_000)
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=170_000, liquidity_usd=48_000
    )
    mem.record_market_tick(
        mint=MINT, observed_at=T0 + timedelta(seconds=600), volume_m5_usd=10_000, liquidity_usd=2_000
    )
    early = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=90))
    assert early["state"] != FAILED


def test_quality_state_idempotent():
    mem = IntelligenceMemory()
    rec = {"mint": MINT, "state": WATCH, "as_of": (T0 + timedelta(seconds=60)).isoformat(), "previous_state": QUNKNOWN}
    assert mem.record_quality_state(rec) is True
    assert mem.record_quality_state(rec) is False
    assert mem.record_quality_state({**rec, "as_of": (T0 + timedelta(seconds=90)).isoformat()}) is False


def test_rug_requires_evidence_and_collapse():
    fade = label_outcome(peak_multiple=1.05, observation_complete=True, drawdown=0.6)
    assert fade.label == FADE
    no_rug = label_outcome(peak_multiple=1.05, observation_complete=True, rug_level="CRITICAL")
    assert no_rug.label != RUG
    rug = label_outcome(
        peak_multiple=1.05, observation_complete=True, rug_level="CRITICAL", liquidity_drop=0.85
    )
    assert rug.label == RUG
    assert rug.label_version.startswith("outcome-v1.1")


def test_runner_threshold_unchanged():
    r = label_outcome(peak_multiple=2.0, observation_complete=True)
    assert r.label == RUNNER
    u = label_outcome(peak_multiple=1.9, observation_complete=True)
    assert u.label != RUNNER


def test_slice_analogues_age_aware():
    mem = IntelligenceMemory()
    rec = slice_analogues(mem, mint=MINT, offset_sec=15, t0=T0)
    assert rec["analogue_count"] == 0
    assert rec["calibrated_probability"] is False
    assert rec["sample_sufficient"] is False


def test_sell_pressure_needs_txns():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=180_000, liquidity_usd=40_000)
    mem.record_market_tick(
        mint=MINT,
        observed_at=T0 + timedelta(seconds=120),
        volume_m5_usd=170_000,
        liquidity_usd=39_000,
        buys=1,
        sells=4,
        txns=5,
    )
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=120))
    assert "buy_sell_pressure" in st["unknown"]
    assert st["is_dip"] is False
