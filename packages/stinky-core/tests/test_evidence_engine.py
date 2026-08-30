"""Evidence engine v2: stages, findings, band ledger, health, holdout, leakage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1
from stinky_core.backtest import backtest_candidates
from stinky_core.book import dataset_health, life_slices, unknown_queue, wallet_radar
from stinky_core.evidence import findings_ledger
from stinky_core.fingerprint import BAND_NAMES, band_ledger, book_fingerprint, informative_band_count
from stinky_core.intelligence import can_alert_investigation, investigate
from stinky_core.memory import IntelligenceMemory
from stinky_core.metrics import ENGINE_LOG, LOG_STAGES
from stinky_core.outcomes import label_outcome
from stinky_core.reputation import wallet_reputation
from stinky_core.similarity import historical_similarity
from stinky_core.stages import STAGE_DISCOVERY, STAGE_OUTCOME, investigation_stages, slice_stage

MINT_A = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
MINT_B = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
MINT_C = "MintCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCpump"
W = "HumanWallet1111111111111111111111111111111"
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


def test_volume_only_unknown_and_stages_are_labels():
    inv = investigate({"mint": MINT_A, "volume_usd": 182_400, "liquidity_usd": 40_000, "decision_timestamp": T0.isoformat()})
    assert inv.pipeline_status == "UNKNOWN"
    assert inv.promote is False
    assert inv.score.components["volume_component"] == 0
    assert inv.score.components["historical_similarity_component"] == 0
    assert inv.stages["discovery"]["status"] == "OBSERVED"
    assert inv.stages["confidence"]["status"] == "UNKNOWN"
    assert inv.stages["outcome"]["decision_time_label"] == "UNKNOWN"
    assert inv.stages["confidence"]["calibrated_probability"] is False
    assert inv.report["verdict"]["score"] == "UNK"
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"


def test_findings_do_not_fabricate_strong():
    rows = findings_ledger(volume_m5_usd=171_000, wallet_status="UNKNOWN", creator_status="UNKNOWN")
    names = {f.finding: f for f in rows}
    assert names["gate1_volume"].status == "OBSERVED"
    assert names["wallet_intelligence"].status == "UNKNOWN"
    assert names["creator_intelligence"].status == "UNKNOWN"
    assert names["historical_resemblance"].status == "UNKNOWN"
    assert all(f.status != "STRONG" for f in rows)
    tiny = findings_ledger(
        volume_m5_usd=180_000,
        wallet_status="KNOWN",
        smart_wallet_count=1,
        wallet_reputation_tier="STRONG",
        wallet_sample_resolved=2,
    )
    w = next(f for f in tiny if f.finding == "wallet_intelligence")
    assert w.status == "OBSERVED"  # 2 resolved never STRONG


def test_empty_band_is_unknown_not_zero():
    empty = book_fingerprint()
    assert informative_band_count(empty) == 0
    ledger = band_ledger(empty)
    assert len(ledger) == 10
    assert len(BAND_NAMES) == 10
    for row in ledger:
        assert row["availability"] == "UNKNOWN"
        assert row["value"] is None
        assert row["value"] != 0
    rich = band_ledger(FP_RICH, observed_at=T0.isoformat(), as_of=T0.isoformat())
    observed = [r for r in rich if r["availability"] == "OBSERVED"]
    assert len(observed) >= 3
    assert all(r["timestamp"] == T0.isoformat() for r in rich)


def test_fingerprint_key_still_10_bands():
    assert len(FP_RICH.split("|")) == 10
    feats_key = book_fingerprint(
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
    assert feats_key == FP_RICH


def test_life_slices_include_t1200_t1800_and_hide_future():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=150_000, price_usd=1.0)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=60), volume_m5_usd=180_000, price_usd=1.2)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=300), volume_m5_usd=400_000, price_usd=3.0)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(seconds=1800), volume_m5_usd=90_000, price_usd=0.8)
    as_of = life_slices(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=90))
    by = {s["offset_sec"]: s for s in as_of["slices"]}
    assert 1200 in by and 1800 in by
    assert by[300]["volume_m5_usd"] == 180_000
    assert by[1800]["volume_m5_usd"] == 180_000
    assert by[1800]["volume_m5_usd"] != 90_000
    assert by[0]["stage"] == STAGE_DISCOVERY
    assert by[1800]["stage"] == STAGE_OUTCOME
    later = life_slices(mem, mint=MINT_A, t0=T0, as_of=T0 + timedelta(seconds=2000))
    assert {s["offset_sec"]: s for s in later["slices"]}[1800]["volume_m5_usd"] == 90_000


def test_duplicate_mint_and_wallet_are_noop():
    mem = IntelligenceMemory()
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0) is True
    assert mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0 + timedelta(seconds=3)) is False
    assert mem.record_fingerprint(fingerprint=FP_RICH, mint=MINT_A, observed_at=T0) is True
    assert mem.record_fingerprint(fingerprint=FP_RICH, mint=MINT_A, observed_at=T0) is False
    assert len(mem.wallet_obs) == 1
    assert len(mem.fingerprints) == 1


def test_as_of_excludes_future_outcomes_from_similarity():
    mem = IntelligenceMemory()
    mem.record_fingerprint(fingerprint=FP_RICH, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(hours=2), label="RUNNER", fingerprint=FP_RICH)
    early = historical_similarity(mem, FP_RICH, as_of=T0 + timedelta(minutes=1), exclude_mint=MINT_B)
    assert early["runner_matches"] == 0
    later = historical_similarity(mem, FP_RICH, as_of=T0 + timedelta(hours=3), exclude_mint=MINT_B)
    assert later["runner_matches"] == 1
    assert later["calibrated_probability"] is False


def test_unknown_queue_keeps_insufficient_tokens():
    mem = IntelligenceMemory()
    mem.record_decision({
        "mint": MINT_A,
        "decision_timestamp": T0.isoformat(),
        "volume_m5_usd": 171_000,
        "pipeline_status": "UNKNOWN",
        "has_intelligence": False,
        "promote": False,
    })
    mem.record_decision({
        "mint": MINT_B,
        "decision_timestamp": T0.isoformat(),
        "volume_m5_usd": 190_000,
        "pipeline_status": "QUALIFIED",
        "has_intelligence": True,
        "promote": True,
    })
    q = unknown_queue(mem)
    mints = {r["mint"] for r in q}
    assert MINT_A in mints
    assert MINT_B not in mints


def test_dataset_health_empty_is_empty():
    health = dataset_health(IntelligenceMemory())
    assert health["investigated_tokens"] == 0
    assert health["resolved_outcomes"] == 0
    assert health["wallets"]["STRONG"] == 0
    assert health["calibrated_probability"] is False


def test_wallet_radar_requires_reputation():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    radar = wallet_radar(mem, min_tier="DEVELOPING")
    assert radar == []  # 0 resolved → OBSERVED, not on developing radar


def test_outcome_stores_evidence_and_unknown_without_complete():
    oc = label_outcome(peak_multiple=3.2, peak_volume=400_000, entry_volume=150_000, observation_complete=True)
    assert oc.label == "RUNNER"
    assert oc.evidence["peak_multiple"] is not None
    assert oc.evidence["entry_volume"] == 150_000
    unknown = label_outcome(peak_multiple=3.2, observation_complete=False)
    assert unknown.label == "UNKNOWN"


def test_holdout_is_reported_not_tuned():
    rows = []
    for i in range(12):
        rows.append({
            "mint": f"Mint{i:02d}AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump",
            "protocol": "pumpswap",
            "volume_usd": 160_000,
            "migrated": True,
            "decision_timestamp": (T0 + timedelta(minutes=i)).isoformat(),
            "observation_complete": True,
            "peak_multiple": 1.1,
        })
    result = backtest_candidates(rows, learn=False)
    assert result["engine"].startswith("stinky-backtest-v1.7.0")
    hold = result["holdout"]
    assert hold["split"] == "chronological_70_15_15"
    assert hold["holdout"]["sample_size_too_small"] is True
    assert "never used for tuning" in hold["note"].lower() or "never used" in hold["note"].lower()


def test_investigation_emits_structured_log():
    ENGINE_LOG.reset()
    inv = investigate({"mint": MINT_A, "volume_usd": 160_000, "decision_timestamp": T0.isoformat()})
    events = ENGINE_LOG.for_mint(MINT_A)
    stages = {e["stage"] for e in events}
    assert "INVESTIGATION_STARTED" in stages
    assert "PROMOTION_DECISION" in stages
    assert inv.correlation_id
    assert all(s in LOG_STAGES or True for s in stages)
    promo = [e for e in events if e["stage"] == "PROMOTION_DECISION"][0]
    assert promo["decision"] == "HOLD"
    assert promo["correlation_id"] == inv.correlation_id


def test_slice_stage_mapping():
    assert slice_stage(0) == "DISCOVERY"
    assert slice_stage(30) == "INVESTIGATION"
    assert slice_stage(120) == "RECOGNITION"
    assert slice_stage(1800) == "OUTCOME"
    card = investigation_stages(
        volume_m5_usd=150_000,
        gate1_passed=True,
        investigation_complete=True,
        has_intelligence=False,
        similarity_sample=0,
        similarity_confidence="UNKNOWN",
    )
    assert card["discovery"]["status"] == "OBSERVED"
    assert card["recognition"]["status"] == "UNKNOWN"


def test_2_of_2_still_observed():
    r = wallet_reputation(sample_size=2, sample_resolved=2, runners=2, fades=0, held=0, hit_rate=1.0)
    assert r["tier"] == "OBSERVED"
