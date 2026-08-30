"""Intelligence book: as-of ledgers, time machine, outcome-from-ticks, advantage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1
from stinky_core.backtest import backtest_candidates
from stinky_core.book import book_stats, creator_book, outcome_from_ticks, pattern_book, time_machine, wallet_book
from stinky_core.fingerprint import book_fingerprint
from stinky_core.intelligence import information_advantage, investigate, why_this_ca
from stinky_core.memory import IntelligenceMemory
from stinky_core.sqlstore import SqliteMemoryStore

MINT_A = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
MINT_B = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
MINT_C = "MintCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCpump"
MINT_D = "MintDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDpump"
MINT_E = "MintEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEpump"
MINT_F = "MintFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFpump"
W = "HumanWallet1111111111111111111111111111111"
W2 = "HumanWallet2222222222222222222222222222222"
CREATOR = "Creator11111111111111111111111111111111111"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _buyers(*ws):
    return [{"wallet": w, "sol_spent": 0.2} for w in ws]


def test_gate1_unchanged():
    assert GATE1_VOLUME_5M_USD == 150_000
    d = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True
    d2 = evaluate_gate1({"mint": MINT_A, "protocol": "pumpswap", "volume_usd": 149_999, "migrated": True})
    assert d2.eligible is False


def test_volume_only_advantage_is_none():
    inv = investigate({"mint": MINT_A, "volume_usd": 183_000})
    adv = information_advantage(inv)
    assert adv["calibrated_probability"] is False
    assert adv["volume_scanner"]["volume_m5_usd"] == 183_000
    assert adv["advantage_status"] in ("NONE", "PARTIAL")
    why = why_this_ca(inv)
    assert inv.promote is False
    assert why["promote"] is False
    assert why["headline"] == "INSUFFICIENT EVIDENCE"
    assert inv.why["headline"] == "INSUFFICIENT EVIDENCE"


def test_wallet_book_as_of_excludes_future():
    mem = IntelligenceMemory()
    mem.record_wallet(wallet=W, mint=MINT_A, observed_at=T0)
    mem.record_outcome(mint=MINT_A, labeled_at=T0 + timedelta(days=2), label="RUNNER", wallets=[W])
    early = wallet_book(mem, as_of=T0 + timedelta(hours=1))
    assert early[0]["hit_rate"] is None
    later = wallet_book(mem, as_of=T0 + timedelta(days=3))
    assert later[0]["runners"] == 1


def test_time_machine_hides_future_outcome():
    mem = IntelligenceMemory()
    for i, mint in enumerate((MINT_A, MINT_B, MINT_C)):
        ts = T0 + timedelta(days=i)
        mem.record_wallet(wallet=W, mint=mint, observed_at=ts)
        mem.record_creator(creator=CREATOR, mint=mint, observed_at=ts)
        mem.record_outcome(mint=mint, labeled_at=ts + timedelta(hours=6), label="RUNNER", wallets=[W], creator=CREATOR)
    view = time_machine(
        mint=MINT_D,
        as_of=T0 + timedelta(days=3),
        bundle={
            "mint": MINT_D,
            "volume_usd": 180_000,
            "buyers": _buyers(W),
            "creator": CREATOR,
        },
        memory=mem,
    )
    assert view["future_hidden"] is True
    assert view["calibrated_probability"] is False
    assert view["known_then"]["wallets"][W]["runners"] == 3
    # D itself is excluded
    assert view["book"]["unique_mints"] >= 1
    assert view["investigation"]["promote"] is True or view["investigation"]["has_intelligence"] is True


def test_outcome_from_ticks_unknown_without_later_path():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=180_000, price_usd=1.0)
    oc = outcome_from_ticks(mem, mint=MINT_A, decision_at=T0, now=T0 + timedelta(minutes=1))
    assert oc["label"] == "UNKNOWN"


def test_outcome_from_ticks_runner_from_later_price():
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=180_000, price_usd=1.0)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(minutes=10), volume_m5_usd=400_000, price_usd=2.5)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(minutes=20), volume_m5_usd=500_000, price_usd=3.1)
    mem.record_market_tick(mint=MINT_A, observed_at=T0 + timedelta(minutes=30), volume_m5_usd=420_000, price_usd=2.8)
    oc = outcome_from_ticks(mem, mint=MINT_A, decision_at=T0, now=T0 + timedelta(hours=2), observation_window=3600)
    assert oc["label"] == "RUNNER"
    assert oc["peak_price_usd"] == 3.1
    assert oc["decision_timestamp"] is not None


def test_pattern_book_tiny_sample_not_probability():
    mem = IntelligenceMemory()
    fp = book_fingerprint(
        top4_wallet_volume_share=0.3, unique_wallets=20, volume_m5_usd=180_000,
        smart_wallet_count=1, creator_launches=5, repeated_size_share=0.1,
        liquidity_usd=40_000, buy_sell_imbalance=0.55, entity_link_count=2, synthetic_level="LOW",
    )
    mem.record_fingerprint(fingerprint=fp, mint=MINT_A, observed_at=T0)
    rows = pattern_book(mem, as_of=T0 + timedelta(days=1))
    assert rows[0]["confidence"] == "UNKNOWN"
    assert rows[0]["calibrated_probability"] is False


def test_sqlite_persists_market_ticks():
    import os, tempfile
    mem = IntelligenceMemory()
    mem.record_market_tick(mint=MINT_A, observed_at=T0, volume_m5_usd=180_000, price_usd=1.0)
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        st = SqliteMemoryStore(path)
        before = st.counts()
        st.persist(mem)
        st.close()
        st2 = SqliteMemoryStore(path)
        after = st2.counts()
        mem2 = st2.load()
        st2.close()
        assert before["market_observations"] == 0
        assert after["market_observations"] == 1
        assert len(mem2.market_ticks) == 1
    finally:
        os.unlink(path)


def test_accumulating_backtest_reports_book_and_advantage():
    mints = [MINT_A, MINT_B, MINT_C, MINT_D, MINT_E, MINT_F]
    rows = []
    for i, mint in enumerate(mints):
        ts = T0 + timedelta(days=i)
        rows.append({
            "mint": mint, "protocol": "pumpswap", "volume_usd": 180_000, "migrated": True,
            "decision_timestamp": ts.isoformat(), "buyers": _buyers(W, W2), "creator": CREATOR,
            "observation_complete": True, "labeled_at": (ts + timedelta(hours=6)).isoformat(),
            "peak_multiple": 3.0,
        })
    result = backtest_candidates(rows, learn=True)
    assert result["engine"].startswith("stinky-backtest-v1.")
    assert result["unique_mints"] == 6
    assert result["items"][0]["promote"] is False
    assert result["items"][-1]["has_intelligence"] is True
    assert result["dataset"][0]["information_advantage"]["calibrated_probability"] is False
    assert "historical_match_count" in result["dataset"][0]
    assert result["book_size"] >= 1
    assert result["mean_advantage_count"] is not None
    assert len(creator_book(IntelligenceMemory())) == 0
