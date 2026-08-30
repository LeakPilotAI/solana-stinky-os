"""Validation/hardening fixtures. Deterministic. No live fabrication."""

from __future__ import annotations

from stinky_core.admission import (
    GATE1_VOLUME_5M_USD,
    GATE1_VOLUME_CALIBRATION_MAX_USD,
    FilterConfig,
    ReasonCode,
    clamp_gate1_volume,
    can_alert,
    evaluate_gate1,
)
from stinky_core.backtest import backtest_candidates, decision_time_snapshot
from stinky_core.inspect import activity_from_trades, assess_synthetic, market_activity_from_mapping
from stinky_core.intelligence import (
    STATUS_UNKNOWN,
    analyze_wallets,
    can_alert_investigation,
    investigate,
    pipeline_status,
)
from stinky_core.pools import is_rankable_wallet

MINT = "AbCdEf1234567890AbCdEf1234567890pump"
POOL = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
HUMAN = "HumanWallet1111111111111111111111111111111"


def _mkt(**kw):
    d = dict(mint=MINT, protocol="pumpswap", volume_usd=150_000.0, migrated=True, tab="migrated")
    d.update(kw)
    return d


def test_gate_boundary_149999():
    d = evaluate_gate1(_mkt(volume_usd=149_999))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_gate_boundary_150000():
    d = evaluate_gate1(_mkt(volume_usd=150_000))
    assert d.eligible is True


def test_gate_maximum_200000():
    d = evaluate_gate1(_mkt(volume_usd=200_000))
    assert d.eligible is True
    assert GATE1_VOLUME_CALIBRATION_MAX_USD == 200_000.0


def test_config_above_200k_rejected():
    assert clamp_gate1_volume(500_000) == 200_000.0
    cfg = FilterConfig(min_volume_usd=500_000)
    assert cfg.min_volume_usd == 200_000.0
    d = evaluate_gate1(_mkt(volume_usd=210_000), min_volume_usd=500_000)
    assert d.eligible is True  # 210k vs clamped 200k
    d2 = evaluate_gate1(_mkt(volume_usd=180_000), min_volume_usd=500_000)
    assert d2.eligible is False  # 180k vs clamped 200k, not vs 500k


def test_missing_volume():
    d = evaluate_gate1(_mkt(volume_usd=None))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.VOLUME_UNKNOWN


def test_negative_volume():
    d = evaluate_gate1(_mkt(volume_usd=-5))
    assert d.eligible is False


def test_invalid_volume():
    d = evaluate_gate1(_mkt(volume_usd="abc"))
    assert d.eligible is False


def test_disabled_protocol():
    d = evaluate_gate1(_mkt(protocol="raydium"))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.PROTOCOL_DISABLED


def test_unknown_fees_not_reject():
    d = evaluate_gate1(_mkt(global_fees_sol=None, global_fees_verified=None))
    assert d.eligible is True
    assert ReasonCode.FEES_UNKNOWN not in d.reason_codes


def test_gate1_is_not_an_alert():
    d = evaluate_gate1(_mkt(volume_usd=400_000))
    assert d.eligible is True
    ok, reason = can_alert(d, score=99, meaningful_buyers=20, inspection_complete=False)
    assert ok is False
    assert reason == ReasonCode.INSPECTION_INCOMPLETE


def test_unknown_intelligence_cannot_alert():
    inv = investigate(_mkt(volume_usd=400_000))
    assert inv.has_intelligence is False
    assert inv.pipeline_status == STATUS_UNKNOWN
    ok, reason = can_alert_investigation(True, inv)
    assert ok is False
    assert reason == "INTELLIGENCE_INSUFFICIENT"
    assert inv.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert inv.runner.score is None


def test_volume_only_is_not_qualified():
    inv = investigate({"mint": MINT, "volume_usd": 400_000})
    assert inv.pipeline_status != "QUALIFIED"
    assert inv.pipeline_status == STATUS_UNKNOWN
    assert pipeline_status(gate1_passed=True, investigation=None) == "DISCOVERED"


def test_synthetic_legitimate_diverse():
    r = assess_synthetic(
        market_activity_from_mapping(
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
    )
    assert r.level == "LOW"


def test_synthetic_concentrated():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "volume_m5_usd": 200_000,
                "unique_wallets": 4,
                "top4_wallet_volume_share": 0.88,
                "trade_count": 40,
                "max_wallet_trades": 5,
            }
        )
    )
    assert r.level in ("HIGH", "CRITICAL")
    assert any(e.signal == "wallet_concentration" for e in r.evidence)


def test_synthetic_repeated_size():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "volume_m5_usd": 180_000,
                "unique_wallets": 20,
                "top4_wallet_volume_share": 0.3,
                "repeated_size_share": 0.7,
            }
        )
    )
    assert any(e.signal == "repetitive_trade_sizes" for e in r.evidence)
    assert r.level not in (None,)


def test_synthetic_circular():
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


def test_synthetic_creator_linked():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "volume_m5_usd": 180_000,
                "unique_wallets": 12,
                "top4_wallet_volume_share": 0.4,
                "creator_linked_share": 0.4,
            }
        )
    )
    assert any(e.signal == "creator_linked_activity" for e in r.evidence)


def test_synthetic_mixed_evidence():
    r = assess_synthetic(
        market_activity_from_mapping(
            {
                "volume_m5_usd": 180_000,
                "unique_wallets": 18,
                "top4_wallet_volume_share": 0.6,
                "repeated_size_share": 0.2,
                "circular_pairs": 1,
            }
        )
    )
    assert r.level in ("MEDIUM", "HIGH")
    assert r.score is not None


def test_synthetic_insufficient_is_unknown_not_low():
    r = assess_synthetic(market_activity_from_mapping({"volume_m5_usd": 200_000, "top4_wallet_volume_share": 0.22}))
    assert r.level == "UNKNOWN"
    assert r.score is None


def test_rug_unknown_without_evidence():
    inv = investigate({"mint": MINT, "volume_usd": 180_000})
    assert inv.rug.level == "UNKNOWN"


def test_insufficient_wallet_history_is_not_smart():
    buyers = [{"wallet": HUMAN, "sol_spent": 0.4}]
    perf = {HUMAN: {"early_buy_count": 1, "tokens_purchased": 1, "hit_rate": 1.0}}
    w = analyze_wallets(buyers, perf)
    assert w.smart_wallet_count == 0
    assert w.status in ("OBSERVED", "UNKNOWN")
    assert w.status != "KNOWN"


def test_insufficient_pattern_history_unknown():
    inv = investigate({"mint": MINT, "volume_usd": 180_000})
    assert inv.patterns.pattern_confidence == "UNKNOWN" or inv.patterns.matches == []


def test_pool_program_exclusion():
    assert is_rankable_wallet(POOL) is False
    w = analyze_wallets(
        [{"wallet": POOL, "sol_spent": 2.0}],
        {POOL: {"early_buy_count": 20, "tokens_purchased": 20, "hit_rate": 0.9}},
    )
    assert w.status == "UNKNOWN"
    assert w.smart_wallet_count in (0, None)


def test_duplicate_transaction_one_logical():
    trades = [
        {"signature": "sig1", "wallet": HUMAN, "type": "buy", "amountSol": 1.0},
        {"signature": "sig1", "wallet": HUMAN, "type": "buy", "amountSol": 1.0},
        {"signature": "sig2", "wallet": HUMAN, "type": "buy", "amountSol": 0.5},
    ]
    act = activity_from_trades(mint=MINT, trades=trades, volume_m5_usd=180_000)
    assert act.duplicate_trades_dropped == 1
    assert act.trade_count == 2


def test_score_attribution_decomposable():
    inv = investigate(
        {
            "mint": MINT,
            "volume_usd": 400_000,
            "unique_wallets": 40,
            "top4_wallet_volume_share": 0.22,
            "repeated_size_share": 0.05,
            "circular_pairs": 0,
            "trade_count": 80,
            "max_wallet_trades": 3,
            "buy_sell_imbalance": 0.55,
            "creator_linked_share": 0.01,
        }
    )
    comps = inv.score.components
    assert "base_score" in comps
    assert "volume_component" in comps
    assert "final_score" in comps
    assert comps["volume_component"] == 0
    assert inv.score.interpretation == "INSUFFICIENT_EVIDENCE"
    assert inv.promote is False
    assert inv.score.to_dict()["calibrated_probability"] is False
    assert inv.runner.to_dict()["calibrated_probability"] is False


def test_future_data_stripped_from_decision():
    row = _mkt(
        volume_usd=20_000,
        peak_volume=900_000,
        peak_multiple=12,
        wallet_performance={HUMAN: {"early_buy_count": 40, "tokens_purchased": 40}},
        historical_patterns={"similar_runner_count": 14},
        buyers=[{"wallet": HUMAN, "sol_spent": 1.0}],
    )
    snap = decision_time_snapshot(row)
    assert "peak_volume" not in snap
    assert "wallet_performance" not in snap
    assert "historical_patterns" not in snap
    result = backtest_candidates([row])
    assert result["gate1_passed"] == 0
    assert result["alerts"] == 0


def test_backtest_uniqueness_coverage_fpr():
    rows = [
        _mkt(volume_usd=20_000, peak_multiple=4.0, observation_complete=True),
        _mkt(volume_usd=20_000, peak_multiple=4.0, observation_complete=True),
        _mkt(mint="OtherMint11111111111111111111111111111pump", volume_usd=10_000),
    ]
    result = backtest_candidates(rows)
    assert result["unique_candidates"] == 2
    assert result["duplicate_mints_dropped"] == 1
    assert result["coverage"] == result["investigated"] / result["unique_candidates"]
    assert "false_positive_rate" in result
    assert "qualified" in result
    assert result["sample_size"] == 2


def test_alert_evidence_complete_fields():
    inv = investigate(_mkt(volume_usd=180_000))
    d = inv.to_dict()
    assert "synthetic" in d and "status" in d["synthetic"]
    assert "rug" in d
    assert "score" in d and "components" in d["score"]
    assert d["runner"]["calibrated_probability"] is False


def test_gate1_threshold_unchanged():
    assert GATE1_VOLUME_5M_USD == 150_000.0
