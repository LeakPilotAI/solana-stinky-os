"""As-of memory, independent synthetic families, promote-never-on-UNKNOWN."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import evaluate_gate1, can_alert
from stinky_core.backtest import backtest_candidates, decision_time_snapshot
from stinky_core.fingerprint import book_fingerprint
from stinky_core.inspect import assess_synthetic, market_activity_from_mapping
from stinky_core.intelligence import (
    STATUS_UNKNOWN,
    analyze_wallets,
    build_creator_profile,
    can_alert_investigation,
    investigate,
)
from stinky_core.memory import IntelligenceMemory
from stinky_core.sqlstore import SqliteMemoryStore

MINT_A = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
MINT_B = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
MINT_C = "MintCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCpump"
MINT_D = "MintDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDpump"
W = "HumanWallet1111111111111111111111111111111"
W2 = "HumanWallet2222222222222222222222222222222"
CREATOR = "Creator11111111111111111111111111111111111"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _buyers(*wallets):
    return [{"wallet": w, "sol_spent": 0.2} for w in wallets]


def test_single_concentration_is_not_high_synthetic():
    r = assess_synthetic(market_activity_from_mapping({
        "volume_m5_usd": 200_000,
        "top4_wallet_volume_share": 0.91,
    }))
    assert r.level in ("UNKNOWN", "MEDIUM")
    assert r.level != "HIGH"
    assert r.level != "CRITICAL"
    assert "concentration" in r.independent_families


def test_two_families_can_be_high():
    r = assess_synthetic(market_activity_from_mapping({
        "volume_m5_usd": 200_000,
        "unique_wallets": 4,
        "top4_wallet_volume_share": 0.81,
        "repeated_size_share": 0.7,
        "circular_pairs": 4,
        "trade_count": 40,
        "max_wallet_trades": 5,
    }))
    assert r.level in ("HIGH", "CRITICAL")
    assert len(r.independent_families) >= 2


def test_creator_tiny_sample_is_observed_not_intelligence():
    p = build_creator_profile({"launch_count": 1, "known": True})
    assert p.status == "OBSERVED"
    inv = investigate({
        "mint": MINT_A,
        "volume_usd": 180_000,
        "creator_profile": {"launch_count": 1, "known": True},
    })
    assert inv.has_intelligence is False
    assert inv.promote is False
    assert inv.pipeline_status == STATUS_UNKNOWN
    assert inv.insufficient_evidence is True


def test_unknown_does_not_promote():
    inv = investigate({"mint": MINT_A, "volume_usd": 400_000})
    assert inv.pipeline_status == STATUS_UNKNOWN
    assert inv.promote is False
    assert inv.score.promotable is False
    assert inv.score.actionable is False
    assert inv.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert inv.runner.score is None
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 400_000, "migrated": True})
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"
    assert can_alert(d, score=inv.score.score, has_intelligence=False, inspection_complete=True)[0] is False
    assert can_alert(d, score=99, meaningful_buyers=20, inspection_complete=True, has_intelligence=False)[1] == "INTELLIGENCE_INSUFFICIENT"


def test_volume_is_not_bullish():
    """$150k and $400k without intelligence must not produce a maybe-buy grade."""
    a = investigate({"mint": MINT_A, "volume_usd": 150_000})
    b = investigate({"mint": MINT_B, "volume_usd": 400_000})
    assert a.promote is False and b.promote is False
    assert a.score.components["volume_component"] == 0
    assert b.score.components["volume_component"] == 0
    assert a.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert b.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert a.runner.score is None and b.runner.score is None
    assert a.score.score == b.score.score
    pos_reasons = " ".join(p["reason"] for p in a.score.positive)
    assert "Gate 1" not in pos_reasons
    assert "volume" not in pos_reasons.lower()
    ok, reason = can_alert_investigation(True, b)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"


def test_observed_buyers_are_not_a_positive():
    inv = investigate({"mint": MINT_A, "volume_usd": 180_000, "buyers": _buyers(W, W2)})
    assert inv.has_intelligence is False
    assert inv.promote is False
    assert (inv.score.components.get("wallet_component") or 0) <= 0
    assert inv.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert inv.runner.score is None


def test_as_of_wallet_excludes_future_outcomes():
    mem = IntelligenceMemory()
    t1 = T0
    t2 = T0 + timedelta(hours=1)
    t3 = T0 + timedelta(hours=2)
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=t1)
    mem.record_wallet(wallet=W, mint=MINT_B, observed_at=t1)
    mem.record_wallet(wallet=W, mint=MINT_C, observed_at=t1)
    # outcomes labeled AFTER t2
    mem.record_outcome(mint=MINT_A, labeled_at=t3, label="RUNNER", wallets=[W])
    mem.record_outcome(mint=MINT_B, labeled_at=t3, label="RUNNER", wallets=[W])
    mem.record_outcome(mint=MINT_C, labeled_at=t3, label="RUNNER", wallets=[W])
    at_t2 = mem.wallet_performance_as_of([W], as_of=t2, exclude_mint=MINT_D)
    assert at_t2[W]["early_buy_count"] == 3
    assert at_t2[W]["hit_rate"] is None  # outcomes not yet labeled
    later = mem.wallet_performance_as_of([W], as_of=t3 + timedelta(seconds=1), exclude_mint=MINT_D)
    assert later[W]["runners"] == 3
    assert later[W]["hit_rate"] == 1.0


def test_as_of_excludes_current_mint():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0, label="RUNNER", wallets=[W])
    perf = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=1), exclude_mint=MINT_A)
    assert perf[W]["early_buy_count"] == 0


def test_future_wallet_row_stripped():
    snap = decision_time_snapshot({
        "mint": MINT_A,
        "volume_usd": 20_000,
        "wallet_performance": {W: {"early_buy_count": 99, "tokens_purchased": 99}},
        "creator_profile": {"launch_count": 99, "historical_runners": 50},
        "peak_volume": 999_000,
    })
    assert "wallet_performance" not in snap
    assert "creator_profile" not in snap
    assert "peak_volume" not in snap


def test_backtest_does_not_leak_future_into_earlier_decision():
    """Wallet becomes smart only after 3 prior labeled outcomes as-of."""
    rows = []
    times = [T0 + timedelta(days=i) for i in range(4)]
    mints = [MINT_A, MINT_B, MINT_C, MINT_D]
    for i, (ts, mint) in enumerate(zip(times, mints)):
        rows.append({
            "mint": mint,
            "protocol": "pumpswap",
            "volume_usd": 180_000,
            "migrated": True,
            "decision_timestamp": ts.isoformat(),
            "buyers": _buyers(W, W2),
            "creator": CREATOR,
            "observation_complete": True,
            "labeled_at": (ts + timedelta(hours=6)).isoformat(),
            "peak_multiple": 3.0,
        })
    result = backtest_candidates(rows, learn=True)
    assert result["unique_mints"] == 4
    assert result["gate1_passed"] == 4
    # First mint: no prior history → UNKNOWN, not promoted
    first = result["items"][0]
    assert first["promote"] is False
    assert first["has_intelligence"] is False
    # Fourth mint: 3 prior observations + outcomes labeled 6h after each prior
    # decision of D is day 3; A,B,C labeled at day0+6h, day1+6h, day2+6h all < day3
    last = result["items"][3]
    assert last["has_intelligence"] is True
    assert last["promote"] is True or last["pipeline_status"] in ("QUALIFIED", "ALERT")


def test_relationship_requires_prior_shared_mints():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    mem.record_wallet(wallet=W2, mint=MINT_A, observed_at=T0)
    mem.record_wallet(wallet=W, mint=MINT_B, observed_at=T0 + timedelta(days=1))
    mem.record_wallet(wallet=W2, mint=MINT_B, observed_at=T0 + timedelta(days=1))
    rel = mem.relationships_as_of([W, W2], as_of=T0 + timedelta(days=2), exclude_mint=MINT_C, min_shared=2)
    assert rel["link_count"] == 1
    assert rel["links"][0]["shared_mints"] == 2
    too_early = mem.relationships_as_of([W, W2], as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_C, min_shared=2)
    assert too_early["link_count"] == 0


def test_fingerprint_sample_too_small_is_unknown():
    mem = IntelligenceMemory()
    fp = book_fingerprint(
        top4_wallet_volume_share=0.3, unique_wallets=20, volume_m5_usd=180_000,
        smart_wallet_count=0, creator_launches=3, repeated_size_share=0.1,
    )
    for i, mint in enumerate((MINT_A, MINT_B, MINT_C)):
        mem.record_fingerprint(fingerprint=fp, mint=mint, observed_at=T0 + timedelta(days=i))
        mem.record_outcome(mint=mint, labeled_at=T0 + timedelta(days=i, hours=1), label="RUNNER", fingerprint=fp)
    hit = mem.pattern_match_as_of(fp, as_of=T0 + timedelta(days=10), exclude_mint=MINT_D, min_sample=5)
    assert hit["similar_runner_count"] is None
    assert hit["confidence"] == "UNKNOWN"


def test_investigate_memory_as_of_does_not_use_future():
    mem = IntelligenceMemory()
    t1 = T0
    t_future = T0 + timedelta(days=10)
    for i, mint in enumerate((MINT_A, MINT_B, MINT_C)):
        mem.record_wallet(wallet=W, mint=mint, observed_at=t1)
        mem.record_outcome(mint=mint, labeled_at=t_future, label="RUNNER", wallets=[W])
    inv = investigate(
        {
            "mint": MINT_D,
            "volume_usd": 180_000,
            "buyers": _buyers(W),
            "decision_timestamp": (T0 + timedelta(days=1)).isoformat(),
            "creator": CREATOR,
        },
        memory=mem,
    )
    # 3 prior observations exist, but outcomes labeled in the future → not smart
    assert (inv.wallets.smart_wallet_count or 0) == 0
    assert inv.promote is False


def test_score_attribution_still_decomposable():
    inv = investigate({
        "mint": MINT_A,
        "volume_usd": 180_000,
        "buyers": _buyers(W),
        "wallet_performance": {
            W: {"early_buy_count": 5, "tokens_purchased": 5, "hit_rate": 0.7, "runners": 4, "fades": 1}
        },
        "wallets_as_of_decision": True,
    })
    assert "volume_component" in inv.score.components
    assert "wallet_component" in inv.score.components
    assert inv.score.calibrated_probability is False if hasattr(inv.score, "calibrated_probability") else True
    assert inv.score.to_dict()["calibrated_probability"] is False
    assert inv.has_intelligence is True
    assert inv.wallets.winner_count == 1
    assert inv.score.interpretation == "EVIDENCE_BASED"
    assert inv.score.actionable is True
    assert inv.score.components["volume_component"] == 0


def test_memory_hydrate_roundtrip():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    mem.record_creator(creator=CREATOR, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0, label="RUNNER", wallets=[W], creator=CREATOR)
    snap = mem.snapshot_rows()
    mem2 = IntelligenceMemory()
    loaded = mem2.hydrate(snap)
    assert loaded["wallet_obs"] == 1
    assert loaded["creator_obs"] == 1
    perf = mem2.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=1), exclude_mint=MINT_B)
    assert perf[W]["runners"] == 1
    assert perf[W]["early_buy_count"] == 1


def test_deployer_buyer_requires_two_prior_mints():
    mem = IntelligenceMemory()
    mem.record_creator(creator=CREATOR, mint=MINT_A, observed_at=T0)
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    one = mem.deployer_buyer_as_of([W], as_of=T0 + timedelta(days=1), exclude_mint=MINT_C)
    assert one == []
    mem.record_creator(creator=CREATOR, mint=MINT_B, observed_at=T0 + timedelta(hours=1))
    mem.record_wallet(wallet=W, mint=MINT_B, observed_at=T0 + timedelta(hours=1))
    two = mem.deployer_buyer_as_of([W], as_of=T0 + timedelta(days=1), exclude_mint=MINT_C)
    assert len(two) == 1
    assert two[0]["kind"] == "deployer_buyer"
    assert two[0]["shared_mints"] == 2
    future = mem.deployer_buyer_as_of([W], as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_C)
    assert future == []


def test_dataset_unique_mint():
    rows = [
        {"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 180_000, "migrated": True, "observation_complete": True, "peak_multiple": 1.1},
        {"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 180_000, "migrated": True},
    ]
    result = backtest_candidates(rows)
    assert result["unique_mints"] == 1
    assert result["duplicate_mints_dropped"] == 1
    assert len(result["dataset"]) == 1
    assert result["dataset"][0]["calibrated_probability"] is False
    assert result["dataset"][0]["promote"] is False
    assert "wallet_features" in result["dataset"][0]
    assert "data_quality" in result["dataset"][0]


def test_wallet_as_of_excludes_future_and_current_and_does_not_fabricate_returns():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0, ret_pct=80.0)
    mem.record_wallet(wallet=W, mint=MINT_B, observed_at=T0 + timedelta(days=1), ret_pct=20.0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(hours=2), label="RUNNER", wallets=[W])
    mem.record_outcome(mint=MINT_B, labeled_at=T0 + timedelta(days=1, hours=2), label="FADE", wallets=[W])
    early = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=1), exclude_mint=MINT_C)
    assert early[W]["tokens_observed"] == 1
    assert early[W]["hit_rate"] is None  # outcome not yet labeled
    assert early[W]["avg_return_pct"] == 80.0
    later = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(days=2), exclude_mint=MINT_C)
    assert later[W]["sample_resolved"] == 2
    assert later[W]["runners"] == 1
    assert later[W]["fades"] == 1
    self_excl = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(days=2), exclude_mint=MINT_B)
    assert self_excl[W]["tokens_observed"] == 1


def test_creator_as_of_launch_n_cannot_see_n():
    mem = IntelligenceMemory()
    for i, mint in enumerate((MINT_A, MINT_B, MINT_C)):
        mem.record_creator(creator=CREATOR, mint=mint, observed_at=T0 + timedelta(days=i))
        mem.record_outcome(mint=mint, labeled_at=T0 + timedelta(days=i, hours=6), label="RUNNER", creator=CREATOR)
    at_c = mem.creator_profile_as_of(CREATOR, as_of=T0 + timedelta(days=2), exclude_mint=MINT_C)
    assert at_c["launch_count"] == 2
    assert at_c["historical_runners"] == 2
    assert at_c["success_rate"] is None  # resolved 2 < 3
    after = mem.creator_profile_as_of(CREATOR, as_of=T0 + timedelta(days=3), exclude_mint=MINT_D)
    assert after["launch_count"] == 3
    assert after["success_rate"] == 1.0


def test_duplicate_wallet_observation_ignored():
    mem = IntelligenceMemory()
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0) is True
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0 + timedelta(minutes=1)) is False
    assert len(mem.wallet_obs) == 1


def test_empty_fingerprint_is_not_resemblance():
    mem = IntelligenceMemory()
    empty = book_fingerprint()
    for i, mint in enumerate((MINT_A, MINT_B, MINT_C, MINT_D, "MintEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEpump")):
        mem.record_fingerprint(fingerprint=empty, mint=mint, observed_at=T0 + timedelta(days=i))
        mem.record_outcome(mint=mint, labeled_at=T0 + timedelta(days=i, hours=1), label="RUNNER", fingerprint=empty)
    hit = mem.pattern_match_as_of(empty, as_of=T0 + timedelta(days=10), exclude_mint="MintFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFpump")
    assert hit["confidence"] == "UNKNOWN"
    assert hit.get("runner_pattern") is False


def test_historical_resemblance_reports_outcome_distribution():
    mem = IntelligenceMemory()
    fp = book_fingerprint(
        top4_wallet_volume_share=0.3, unique_wallets=20, volume_m5_usd=180_000,
        smart_wallet_count=1, creator_launches=5, repeated_size_share=0.1,
        liquidity_usd=40_000, buy_sell_imbalance=0.55, entity_link_count=2, synthetic_level="LOW",
    )
    mints = [MINT_A, MINT_B, MINT_C, MINT_D, "MintEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEpump", "MintFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFpump"]
    labels = ["RUNNER", "RUNNER", "RUNNER", "HELD", "FADE", "UNKNOWN"]
    for i, (mint, lab) in enumerate(zip(mints, labels)):
        mem.record_fingerprint(fingerprint=fp, mint=mint, observed_at=T0 + timedelta(days=i))
        mem.record_outcome(mint=mint, labeled_at=T0 + timedelta(days=i, hours=1), label=lab, fingerprint=fp)
    hit = mem.pattern_match_as_of(fp, as_of=T0 + timedelta(days=20), exclude_mint="MintGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGpump")
    assert hit["sample_count"] == 6
    assert hit["runner_matches"] == 3
    assert hit["held_matches"] == 1
    assert hit["fade_matches"] == 1
    assert hit["unknown_matches"] == 1
    assert hit["runner_pattern"] is True
    assert hit["fade_pattern"] is False
    assert hit["calibrated_probability"] is False
    assert len(hit["matching_historical_mints"]) == 6


def test_sqlite_restart_hydration_reconstructs_as_of():
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        store = SqliteMemoryStore(path)
        mem = IntelligenceMemory()
        mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
        mem.record_wallet(wallet=W, mint=MINT_B, observed_at=T0)
        mem.record_wallet(wallet=W, mint=MINT_C, observed_at=T0)
        mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(hours=1), label="RUNNER", wallets=[W])
        mem.record_outcome(mint=MINT_B, labeled_at=T0 + timedelta(hours=1), label="RUNNER", wallets=[W])
        mem.record_outcome(mint=MINT_C, labeled_at=T0 + timedelta(hours=1), label="RUNNER", wallets=[W])
        mem.record_creator(creator=CREATOR, mint=MINT_A, observed_at=T0)
        before = store.counts()
        store.persist(mem)
        after = store.counts()
        store.close()
        store2 = SqliteMemoryStore(path)
        mem2 = store2.load()
        store2.close()
        perf = mem2.wallet_performance_as_of([W], as_of=T0 + timedelta(days=1), exclude_mint=MINT_D)
        assert perf[W]["sample_resolved"] == 3
        assert perf[W]["hit_rate"] == 1.0
        inv = investigate(
            {
                "mint": MINT_D,
                "volume_usd": 180_000,
                "buyers": _buyers(W),
                "decision_timestamp": (T0 + timedelta(days=1)).isoformat(),
                "creator": CREATOR,
            },
            memory=mem2,
        )
        assert inv.has_intelligence is True
        assert inv.promote is True or inv.pipeline_status in ("QUALIFIED", "ALERT")
        assert after["wallet_observations"] >= before["wallet_observations"]
        assert after["wallet_observations"] == 3
    finally:
        os.unlink(path)


def test_data_quality_unknown_when_no_intel():
    inv = investigate({"mint": MINT_A, "volume_usd": 180_000})
    assert inv.data_quality["overall"] in ("UNKNOWN", "LOW")
    assert inv.data_quality["layers"]["wallets"]["confidence"] == "UNKNOWN"
    assert inv.promote is False


def test_returns_never_invented_without_stored_pct():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0, entry_price=None, exit_price=None)
    perf = mem.wallet_performance_as_of([W], as_of=T0 + timedelta(hours=1), exclude_mint=MINT_B)
    assert perf[W]["avg_return_pct"] is None
    assert perf[W]["median_return_pct"] is None
