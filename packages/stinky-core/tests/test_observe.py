"""Live observation, recipes, insights, leakage, duplicates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, clamp_gate1_volume, evaluate_gate1
from stinky_core.backtest import backtest_candidates
from stinky_core.book import LIFE_SLICES_SEC, dataset_health, life_slices, what_happened_next
from stinky_core.intelligence import can_alert_investigation, investigate
from stinky_core.insights import candidate_insights
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import investigation_record, observation_slices
from stinky_core.recipes import runner_recipe
from stinky_core.sqlstore import SqliteMemoryStore

MINT_A = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
MINT_B = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
W = "HumanWallet1111111111111111111111111111111"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_gate1_unchanged_and_clamp():
    assert GATE1_VOLUME_5M_USD == 150_000
    assert clamp_gate1_volume(250_000) == 200_000
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 149_999, "migrated": True})
    assert d.eligible is False


def test_life_slices_include_t15():
    assert 15 in LIFE_SLICES_SEC
    assert 1800 in LIFE_SLICES_SEC


def test_investigation_record_is_immutable():
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 172_000, "liquidity_usd": 40_000,
         "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
        investigation_status="UNKNOWN",
    )
    assert rec["immutable"] is True
    assert rec["volume_5m_at_gate"] == 172_000
    assert rec["market_cap_at_gate"] is None
    assert mem.record_investigation(rec) is True
    rec2 = dict(rec)
    rec2["volume_5m_at_gate"] = 999_999
    assert mem.record_investigation(rec2) is False
    assert mem.investigations[0]["volume_5m_at_gate"] == 172_000


def test_duplicate_tick_is_noop():
    mem = IntelligenceMemory()
    assert mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=150_000, buys=20, sells=8) is True
    assert mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=999_000) is False
    assert len(mem.market_ticks) == 1
    assert mem.market_ticks[0].buys == 20
    assert mem.market_ticks[0].buy_sell_ratio == 0.7143


def test_missing_tick_fields_stay_unknown():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=160_000)
    path = observation_slices(mem, mint=MINT_A, t0=T0)
    by = {s["offset_sec"]: s for s in path["slices"]}
    assert by[0]["volume_5m"] == 160_000
    assert by[0]["unique_buyers"] is None
    assert by[15]["volume_5m"] == 160_000  # last-known carry-forward, not interpolated
    assert by[15]["unique_buyers"] is None
    assert "price" in by[0]["missing"]


def test_future_ticks_hidden_from_what_happened_next():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=165_000, price_usd=1.0)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=97_000, price_usd=0.7)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=690_000, price_usd=4.0)
    early = what_happened_next(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=90))
    assert early["peak_volume"] == 97_000
    assert early["peak_volume"] != 690_000
    full = what_happened_next(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=400))
    assert full["peak_volume"] == 690_000
    assert full["outcome"]["label"] in ("RUNNER", "HELD", "FADE", "UNKNOWN")


def test_empty_fingerprint_has_no_recipe():
    rec = runner_recipe(IntelligenceMemory(), "CU|DU|SU|XU|PU|LU|RU|BU|EU|YU")
    assert rec["analogue_count"] == 0
    assert rec["calibrated_probability"] is False
    assert rec["sample_sufficient"] is False if "sample_sufficient" in rec else True
    assert rec["runner_count"] == 0


def test_recipe_as_of_excludes_future_and_current_mint():
    from stinky_core.fingerprint import book_fingerprint

    fp = book_fingerprint(
        top4_wallet_volume_share=0.40, unique_wallets=20, volume_m5_usd=180_000,
        smart_wallet_count=3, creator_launches=5, repeated_size_share=0.20,
        liquidity_usd=40_000, buy_sell_imbalance=0.52, entity_link_count=2, synthetic_level="LOW",
    )
    mem = IntelligenceMemory()
    mem.record_fingerprint(fingerprint=fp, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(hours=2), label="RUNNER", fingerprint=fp)
    early = runner_recipe(mem, fp, as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_B)
    assert early["runner_count"] == 0
    later = runner_recipe(mem, fp, as_of=T0 + timedelta(hours=4), exclude_mint=MINT_B)
    assert later["analogue_count"] >= 1
    self_ex = runner_recipe(mem, fp, as_of=T0 + timedelta(hours=4), exclude_mint=MINT_A)
    assert self_ex["analogue_count"] == 0


def test_volume_only_still_unknown():
    inv = investigate({"mint": MINT_A, "volume_usd": 182_000, "liquidity_usd": 41_000})
    assert inv.pipeline_status == "UNKNOWN"
    assert inv.promote is False
    assert inv.score.actionable is False
    assert inv.investigation_record["immutable"] is True
    assert inv.recipe["calibrated_probability"] is False
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"


def test_pool_wallet_not_smart_money():
    inv = investigate({
        "mint": MINT_A,
        "volume_usd": 180_000,
        "buyers": [{"wallet": "So11111111111111111111111111111111111111112", "sol_spent": 10}],
    })
    assert inv.wallets.smart_wallet_count in (0, None)
    assert inv.has_intelligence is False


def test_insights_holdout_excluded_and_not_promoted():
    rows = [
        {"mint": f"m{i}", "outcome_label": "RUNNER" if i % 2 else "FADE",
         "pattern_features": {"pattern_matches": [{"kind": "dense_early_book"}]}}
        for i in range(24)
    ]
    hold = [f"m{i}" for i in range(20, 24)]
    out = candidate_insights(rows, holdout_mints=hold)
    assert out["skipped_holdout"] == 4
    assert out["promoted_to_score"] is False
    assert out["human_review_required"] is True
    assert out["sample"] == 20


def test_insights_tiny_sample_is_unknown():
    out = candidate_insights([{"mint": "a", "outcome_label": "RUNNER"}] * 5)
    assert out["candidates"] == []
    assert "TOO SMALL" in out["note"]


def test_sqlite_persists_investigations_and_rich_ticks(tmp_path):
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT_A, "volume_usd": 170_000, "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
    )
    mem.record_investigation(rec)
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=170_000, buys=12, sells=4, market_cap_usd=80_000)
    path = tmp_path / "obs.sqlite"
    store = SqliteMemoryStore(path)
    store.persist(mem)
    mem2 = store.load()
    store.close()
    assert len(mem2.investigations) == 1
    assert mem2.investigations[0]["volume_5m_at_gate"] == 170_000
    assert mem2.market_ticks[0].buys == 12
    assert mem2.market_ticks[0].market_cap_usd == 80_000


def test_health_warnings_on_empty_and_tiny_sample():
    empty = dataset_health(IntelligenceMemory())
    assert any("No Gate 1" in w for w in empty["warnings"])
    mem = IntelligenceMemory()
    mem.record_decision({"mint": MINT_A, "decision_timestamp": T0.isoformat(), "pipeline_status": "UNKNOWN", "volume_m5_usd": 160_000})
    h = dataset_health(mem)
    assert any("too small" in w.lower() or "RUNNER" in w for w in h["warnings"])


def test_backtest_insights_not_used_for_tuning():
    markets = [
        {"mint": f"Mint{i:02d}AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump", "protocol": "pumpswap",
         "volume_usd": 160_000, "migrated": True, "decision_timestamp": (T0 + timedelta(minutes=i)).isoformat(),
         "observation_complete": True, "peak_multiple": 2.5 if i % 3 == 0 else 1.1}
        for i in range(12)
    ]
    out = backtest_candidates(markets)
    assert out["engine"].startswith("stinky-backtest-v1.8")
    assert out["insights"]["promoted_to_score"] is False
    assert out["holdout"]["calibrated_probability"] is False


def test_life_slices_t15_carry_forward_not_future():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=150_000)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=30), volume_m5_usd=180_000)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=400_000)
    sl = life_slices(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=20))
    by = {s["offset_sec"]: s for s in sl["slices"]}
    assert by[15]["volume_m5_usd"] == 150_000
    assert by[30]["volume_m5_usd"] == 150_000
    assert by[300]["volume_m5_usd"] != 400_000
