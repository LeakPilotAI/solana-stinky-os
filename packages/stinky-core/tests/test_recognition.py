"""Recognition v2: reputation floors, similarity, life slices, leakage, unknown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1
from stinky_core.book import life_slices
from stinky_core.fingerprint import book_fingerprint, informative_band_count, matching_informative_bands
from stinky_core.intelligence import can_alert_investigation, investigate
from stinky_core.memory import IntelligenceMemory
from stinky_core.reputation import creator_reputation, wallet_reputation
from stinky_core.similarity import historical_similarity

MINT_A = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
MINT_B = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
MINT_C = "MintCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCpump"
MINT_D = "MintDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDpump"
MINT_E = "MintEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEpump"
MINT_F = "MintFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFpump"
W = "HumanWallet1111111111111111111111111111111"
CREATOR = "Creator11111111111111111111111111111111111"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

FP_RICH = book_fingerprint(
    top4_wallet_volume_share=0.40,
    unique_wallets=20,
    volume_m5_usd=180_000,
    smart_wallet_count=3,
    creator_launches=5,
    repeated_size_share=0.20,
    liquidity_usd=40_000,
    buy_sell_imbalance=0.52,
    entity_link_count=2,
    synthetic_level="LOW",
)


def test_gate1_unchanged():
    assert GATE1_VOLUME_5M_USD == 150_000
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 149_999, "migrated": True})
    assert d.eligible is False
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True


def test_wallet_one_and_two_trades_observed_not_strong():
    a = wallet_reputation(sample_size=1, sample_resolved=1, runners=1, fades=0, held=0, hit_rate=1.0)
    b = wallet_reputation(sample_size=2, sample_resolved=2, runners=2, fades=0, held=0, hit_rate=1.0)
    assert a["tier"] == "OBSERVED"
    assert b["tier"] == "OBSERVED"
    assert a["confidence"] is None
    assert b["calibrated_probability"] is False


def test_wallet_developing_measured_strong():
    dev = wallet_reputation(sample_size=4, sample_resolved=4, runners=2, fades=1, held=1, hit_rate=0.5)
    meas = wallet_reputation(sample_size=10, sample_resolved=10, runners=4, fades=4, held=2, hit_rate=0.4)
    strong = wallet_reputation(sample_size=20, sample_resolved=16, runners=8, fades=5, held=3, hit_rate=0.5)
    not_strong = wallet_reputation(sample_size=20, sample_resolved=16, runners=2, fades=12, held=2, hit_rate=0.12)
    assert dev["tier"] == "DEVELOPING"
    assert meas["tier"] == "MEASURED"
    assert strong["tier"] == "STRONG"
    assert not_strong["tier"] == "MEASURED"


def test_creator_reputation_floors():
    assert creator_reputation(launches=0)["tier"] == "UNKNOWN"
    assert creator_reputation(launches=1, runners=1)["tier"] == "OBSERVED"
    assert creator_reputation(launches=5, runners=1, fades=1, held=0)["tier"] == "DEVELOPING"
    measured = creator_reputation(launches=8, runners=2, fades=1, held=1, success_rate=0.5)
    assert measured["tier"] == "MEASURED"
    hi = creator_reputation(launches=10, runners=5, fades=1, held=1, success_rate=0.7)
    assert hi["tier"] == "HIGH_CONFIDENCE"
    serial = creator_reputation(launches=20, runners=8, fades=4, held=2, success_rate=0.57)
    assert serial["tier"] == "HIGH_RISK"
    poor = creator_reputation(launches=10, runners=0, fades=6, held=0, success_rate=0.0)
    assert poor["tier"] == "HIGH_RISK"


def test_empty_fingerprint_not_resemblance():
    mem = IntelligenceMemory()
    hit = historical_similarity(mem, "CU|DU|SU|XU|PU|LU|RU|BU|EU|YU", as_of=T0, exclude_mint=MINT_A)
    assert hit["similarity_confidence"] == "UNKNOWN"
    assert hit["strong_matches"] == 0
    assert hit["calibrated_probability"] is False
    assert informative_band_count("CU|DU|SU|XU|PU|LU|RU|BU|EU|YU") < 3


def test_similarity_shows_all_classes_not_just_runners():
    mem = IntelligenceMemory()
    assert informative_band_count(FP_RICH) >= 3
    mints = [MINT_A, MINT_B, MINT_C, MINT_D, MINT_E, MINT_F]
    labels = ["RUNNER", "RUNNER", "FADE", "HELD", "UNKNOWN", "RUNNER"]
    for i, (m, lab) in enumerate(zip(mints, labels)):
        ts = T0 + timedelta(days=i)
        mem.record_fingerprint(fingerprint=FP_RICH, mint=m, observed_at=ts)
        mem.record_outcome(mint=m, labeled_at=ts + timedelta(hours=2), label=lab, fingerprint=FP_RICH)
    later = T0 + timedelta(days=10)
    hit = historical_similarity(mem, FP_RICH, as_of=later, exclude_mint="MintZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZpump")
    assert hit["runner_matches"] >= 1
    assert hit["fade_matches"] >= 1
    assert hit["held_matches"] >= 1
    assert hit["unknown_matches"] >= 1
    assert hit["calibrated_probability"] is False
    assert hit["strong_matches"] >= 5
    outcomes = {m["outcome"] for m in hit["historical_matches"]}
    assert "RUNNER" in outcomes and "FADE" in outcomes


def test_similarity_exact_partial_none():
    mem = IntelligenceMemory()
    mem.record_fingerprint(fingerprint=FP_RICH, mint=MINT_A, observed_at=T0)
    other = book_fingerprint(
        top4_wallet_volume_share=0.40,
        unique_wallets=20,
        volume_m5_usd=180_000,
        smart_wallet_count=0,
        creator_launches=0,
        repeated_size_share=0.20,
        liquidity_usd=40_000,
        buy_sell_imbalance=0.52,
        entity_link_count=0,
        synthetic_level="LOW",
    )
    mem.record_fingerprint(fingerprint=other, mint=MINT_B, observed_at=T0)
    later = T0 + timedelta(hours=1)
    hit = historical_similarity(mem, FP_RICH, as_of=later, exclude_mint=MINT_C)
    # one exact + maybe partial; sample < 5 so confidence UNKNOWN
    assert hit["similarity_confidence"] == "UNKNOWN"
    none_fp = book_fingerprint(volume_m5_usd=180_000, liquidity_usd=9_000, unique_wallets=30, top4_wallet_volume_share=0.10)
    miss = historical_similarity(mem, none_fp, as_of=later, exclude_mint=MINT_C)
    assert miss["strong_matches"] == 0


def test_future_fingerprint_does_not_leak():
    mem = IntelligenceMemory()
    mem.record_fingerprint(fingerprint=FP_RICH, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(hours=3), label="RUNNER", fingerprint=FP_RICH)
    early = historical_similarity(mem, FP_RICH, as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_B)
    assert early["runner_matches"] == 0  # outcome labeled later
    later = historical_similarity(mem, FP_RICH, as_of=T0 + timedelta(hours=4), exclude_mint=MINT_B)
    assert later["runner_matches"] == 1


def test_life_slices_hide_future_ticks():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=150_000, price_usd=1.0, liquidity_usd=20_000)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=180_000, price_usd=1.2, liquidity_usd=22_000)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=400_000, price_usd=3.0, liquidity_usd=30_000)
    at_60 = life_slices(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=90))
    by = {s["offset_sec"]: s for s in at_60["slices"]}
    assert by[0]["volume_m5_usd"] == 150_000
    assert by[60]["volume_m5_usd"] == 180_000
    assert by[300]["volume_m5_usd"] == 180_000  # last known as-of T+90s, not the future 400k
    assert by[300]["volume_m5_usd"] != 400_000
    full = life_slices(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=400))
    assert {s["offset_sec"]: s for s in full["slices"]}[300]["volume_m5_usd"] == 400_000


def test_volume_only_still_unknown_and_not_alerted():
    inv = investigate({"mint": MINT_A, "volume_usd": 220_000, "liquidity_usd": 40_000})
    assert inv.pipeline_status == "UNKNOWN"
    assert inv.promote is False
    assert inv.score.actionable is False
    assert inv.runner.score is None
    assert inv.score.components["volume_component"] == 0
    assert inv.score.components["historical_similarity_component"] == 0
    assert inv.report["verdict"]["score"] == "UNK"
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"


def test_duplicate_wallet_observation_is_noop():
    mem = IntelligenceMemory()
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0) is True
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0 + timedelta(seconds=5)) is False
    assert len(mem.wallet_obs) == 1


def test_as_of_wallet_reputation_excludes_future_and_current_mint():
    mem = IntelligenceMemory()
    for i, m in enumerate((MINT_A, MINT_B, MINT_C)):
        mem.record_wallet(wallet=W, mint=m, observed_at=T0)
        mem.record_outcome(mint=m, labeled_at=T0 + timedelta(hours=2), label="RUNNER", wallets=[W])
    early = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_D)
    assert early[W]["reputation_tier"] == "OBSERVED"  # outcomes not yet labeled
    later = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=3), exclude_mint=MINT_D)
    assert later[W]["sample_resolved"] == 3
    assert later[W]["reputation_tier"] == "DEVELOPING"
    self_excl = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=3), exclude_mint=MINT_A)
    assert self_excl[W]["sample_resolved"] == 2


def test_matching_bands_do_not_expand_key():
    a = FP_RICH
    b = FP_RICH
    shared = matching_informative_bands(a, b)
    assert len(a.split("|")) == 10
    assert len(shared) >= 3


def test_report_does_not_promote_volume():
    inv = investigate({"mint": MINT_A, "volume_usd": 400_000})
    assert inv.report["promote"] is False
    assert inv.report["verdict"]["score"] == "UNK"
    assert inv.report["historical_matches"]["calibrated_probability"] is False
