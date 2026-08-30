"""Deterministic intelligence pipeline tests. No fabricated live data."""

from __future__ import annotations

from stinky_core.admission import GATE1_VOLUME_5M_USD, ReasonCode, can_alert, evaluate_gate1
from stinky_core.inspect import assess_synthetic, market_activity_from_mapping
from stinky_core.intelligence import (
    STATUS_HIGH_RISK,
    analyze_wallets,
    build_creator_profile,
    can_alert_investigation,
    investigate,
    match_patterns,
)


def test_synthetic_high_concentration():
    act = market_activity_from_mapping(
        {
            "volume_m5_usd": 200_000,
            "unique_wallets": 4,
            "top4_wallet_volume_share": 0.81,
            "trade_count": 40,
            "max_wallet_trades": 5,
        }
    )
    r = assess_synthetic(act)
    assert r.score is not None
    assert r.level in ("HIGH", "CRITICAL")
    assert any(e.signal == "wallet_concentration" for e in r.evidence)


def test_synthetic_diverse_book_low():
    act = market_activity_from_mapping(
        {
            "volume_m5_usd": 200_000,
            "unique_wallets": 40,
            "top4_wallet_volume_share": 0.22,
            "repeated_size_share": 0.05,
            "circular_pairs": 0,
            "max_wallet_trades": 3,
            "trade_count": 80,
            "buy_sell_imbalance": 0.55,
            "creator_linked_share": 0.01,
        }
    )
    r = assess_synthetic(act)
    assert r.level == "LOW"


def test_synthetic_unknown_without_flow():
    r = assess_synthetic(market_activity_from_mapping({"volume_m5_usd": 200_000}))
    assert r.level == "UNKNOWN"
    assert r.score is None


def test_repetitive_trades():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "volume_m5_usd": 180_000,
                "unique_wallets": 20,
                "top4_wallet_volume_share": 0.3,
                "repeated_size_share": 0.7,
                "circular_pairs": 0,
                "trade_count": 30,
                "max_wallet_trades": 2,
            }
        )
    )
    assert any(e.signal == "repetitive_trade_sizes" for e in r.evidence)


def test_circular_activity():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "unique_wallets": 10,
                "volume_m5_usd": 160_000,
                "top4_wallet_volume_share": 0.4,
                "circular_pairs": 4,
            }
        )
    )
    assert any(e.signal == "circular_activity" for e in r.evidence)


def test_creator_unknown():
    p = build_creator_profile(None)
    assert p.status == "UNKNOWN"
    p2 = build_creator_profile({})
    assert p2.status == "UNKNOWN"


def test_creator_known_serial():
    p = build_creator_profile({"launch_count": 37, "historical_runners": 8, "historical_fades": 17, "wallet_count": 4})
    assert p.status == "KNOWN"
    assert p.launches == 37
    assert p.serial_risk == "MEDIUM"


def test_wallet_unknown():
    w = analyze_wallets(None)
    assert w.status == "UNKNOWN"


def test_wallet_known_winner():
    buyers = [{"wallet": "HumanWallet1111111111111111111111111111111", "sol_spent": 0.4}]
    perf = {
        "HumanWallet1111111111111111111111111111111": {
            "early_buy_count": 6,
            "tokens_purchased": 6,
            "hit_rate": 0.7,
            "avg_return_pct": 80,
        }
    }
    w = analyze_wallets(buyers, perf)
    assert w.status == "KNOWN"
    assert w.smart_wallet_count == 1
    assert w.meaningful_buyer_count == 1


def test_pattern_insufficient_data():
    inv = investigate({"mint": "AbCdEf1234567890AbCdEf1234567890pump", "volume_usd": 180_000})
    assert inv.patterns.pattern_confidence == "UNKNOWN" or inv.patterns.matches == []


def test_pattern_known():
    buyers = [{"wallet": f"W{i:02d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "sol_spent": 0.2} for i in range(8)]
    perf = {
        b["wallet"]: {"early_buy_count": 5, "tokens_purchased": 5, "hit_rate": 0.6}
        for b in buyers[:4]
    }
    inv = investigate(
        {
            "mint": "AbCdEf1234567890AbCdEf1234567890pump",
            "volume_usd": 180_000,
            "buyers": buyers,
            "wallet_performance": perf,
            "creator_profile": {"launch_count": 10, "historical_runners": 3},
        }
    )
    kinds = {m["kind"] for m in inv.patterns.matches}
    assert "dense_early_book" in kinds or "measured_edge" in kinds


def test_investigate_does_not_fabricate_fees():
    inv = investigate({"mint": "AbCdEf1234567890AbCdEf1234567890pump", "volume_usd": 180_000})
    assert inv.global_fees_sol is None
    assert inv.fee_status == "UNKNOWN"


def test_gate1_pass_is_not_an_alert():
    d = evaluate_gate1(
        {
            "mint": "AbCdEf1234567890AbCdEf1234567890pump",
            "protocol": "pumpswap",
            "volume_usd": 180_000,
            "migrated": True,
        }
    )
    assert d.eligible is True
    ok, reason = can_alert(d, score=99, meaningful_buyers=20, inspection_complete=False)
    assert ok is False
    assert reason == ReasonCode.INSPECTION_INCOMPLETE


def test_critical_synthetic_cannot_alert():
    buyers = [{"wallet": "Samexxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "sol_spent": 1.0} for _ in range(3)]
    inv = investigate(
        {
            "mint": "AbCdEf1234567890AbCdEf1234567890pump",
            "volume_usd": 200_000,
            "unique_wallets": 3,
            "top4_wallet_volume_share": 0.95,
            "repeated_size_share": 0.8,
            "circular_pairs": 5,
            "trade_count": 40,
            "max_wallet_trades": 20,
            "buyers": buyers,
        }
    )
    assert inv.synthetic.level in ("HIGH", "CRITICAL")
    d = evaluate_gate1(
        {
            "mint": "AbCdEf1234567890AbCdEf1234567890pump",
            "protocol": "pump",
            "volume_usd": 200_000,
            "migrated": True,
        }
    )
    ok, reason = can_alert_investigation(d.eligible, inv)
    if inv.synthetic.level == "CRITICAL" or inv.rug.level == "CRITICAL":
        assert ok is False
        assert reason == "RISK_CRITICAL"


def test_volume_only_insufficient_intelligence():
    inv = investigate({"mint": "AbCdEf1234567890AbCdEf1234567890pump", "volume_usd": 200_000})
    d = evaluate_gate1(
        {
            "mint": "AbCdEf1234567890AbCdEf1234567890pump",
            "protocol": "pump",
            "volume_usd": 200_000,
            "migrated": True,
        }
    )
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason in ("INTELLIGENCE_INSUFFICIENT", "SCORE_BELOW_MIN")


def test_gate1_constant():
    assert GATE1_VOLUME_5M_USD == 150_000.0
