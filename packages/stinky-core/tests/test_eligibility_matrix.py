"""Required eligibility matrix — axiom-parity-v1.0.0.

These are product requirements, not suggestions.
"""

from __future__ import annotations

from stinky_core.admission import (
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    FILTER_VERSION,
    ReasonCode,
    can_alert,
    evaluate_admission,
    evaluate_market,
    filter_stats,
)
from stinky_core.backtest import backtest_candidates
from stinky_core.identity import UniqueMintIndex
from stinky_core.outcomes import FADE, HELD, RUNNER, UNKNOWN, label_outcome
from stinky_core.pools import is_rankable_wallet

MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def _base(**kw):
    d = dict(
        mint=MINT,
        protocol="pumpfun",
        global_fees_sol=3.0,
        global_fees_verified=True,
        global_fees_source="pump.fun/total_fees",
        liquidity_usd=20.0,
        volume_usd=150_000.0,
        market_cap_usd=50_000.0,
        twitter="https://x.com/abc",
        migrated=True,
        tab="migrated",
    )
    d.update(kw)
    return d


def setup_function() -> None:
    filter_stats.reset()


# --- 1-6 fees ---


def test_fees_0_00_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.00))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN
    assert ReasonCode.FEES_BELOW_MIN in d.reason_codes


def test_fees_0_50_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.50))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_fees_0_99_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.99))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_fees_1_00_pass_fee_gate():
    d = evaluate_admission(**_base(global_fees_sol=1.00))
    assert d.eligible is True
    assert d.rejection_reason is None
    assert any(f["name"] == "global_fees" and f["passed"] for f in d.passed_filters)


def test_fees_3_00_pass_fee_gate():
    d = evaluate_admission(**_base(global_fees_sol=3.00))
    assert d.eligible is True


def test_missing_fees_reject():
    d = evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_unverified_fees_reject():
    d = evaluate_admission(**_base(global_fees_sol=12.0, global_fees_verified=False))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


# --- 7-8 liquidity ---


def test_liquidity_7_99_reject():
    d = evaluate_admission(**_base(liquidity_usd=7.99))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.LIQUIDITY_BELOW_MIN


def test_liquidity_8_00_pass():
    d = evaluate_admission(**_base(liquidity_usd=8.00))
    assert d.eligible is True


# --- 9-10 volume ---


def test_volume_99999_reject():
    d = evaluate_admission(**_base(volume_usd=99_999))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_volume_100000_pass():
    d = evaluate_admission(**_base(volume_usd=100_000))
    assert d.eligible is True


# --- 11-12 market cap ---


def test_market_cap_31332_99_reject():
    d = evaluate_admission(**_base(market_cap_usd=31_332.99))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.MARKET_CAP_BELOW_MIN


def test_market_cap_31333_pass():
    d = evaluate_admission(**_base(market_cap_usd=31_333))
    assert d.eligible is True


# --- 13-14 protocol ---


def test_disabled_protocol_reject():
    for proto in ("raydium", "pumpAmm", "meteoraAmmV2", "orca"):
        d = evaluate_admission(**_base(protocol=proto))
        assert d.eligible is False, proto
        assert d.rejection_reason == ReasonCode.PROTOCOL_DISABLED


def test_unknown_protocol_reject():
    d = evaluate_admission(**_base(protocol=None, dex_id=None))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.PROTOCOL_UNKNOWN


# --- 15 social ---


def test_no_social_reject():
    d = evaluate_admission(
        **_base(twitter=None, website=None, telegram=None, tiktok=None, socials=None)
    )
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.NO_SOCIAL


# --- 16 duplicate mint ---


def test_duplicate_mint_one_candidate():
    idx = UniqueMintIndex()
    assert idx.add(MINT) is True
    assert idx.add(MINT) is False
    assert idx.add("  " + MINT) is False
    assert len(idx) == 1
    result = backtest_candidates([_base(), _base(), _base(mint=MINT)])
    assert result["unique_mints"] == 1
    assert result["duplicate_mints_dropped"] == 2


# --- 21 backtest == live ---


def test_backtest_and_live_filter_identical():
    market = _base(global_fees_sol=0.42)
    live = evaluate_market(market)
    bt = evaluate_market(market)
    assert live.eligible is False
    assert bt.eligible is False
    assert live.rejection_reason == bt.rejection_reason == ReasonCode.FEES_BELOW_MIN
    assert live.reason_codes == bt.reason_codes
    passing = _base(global_fees_sol=1.0)
    assert evaluate_market(passing).eligible is evaluate_admission(**passing).eligible is True


# --- 22 alert cannot bypass ---


def test_alert_cannot_bypass_eligibility_gate():
    d = evaluate_admission(**_base(global_fees_sol=0.2))
    ok, reason = can_alert(d, score=99, meaningful_buyers=20)
    assert d.eligible is False
    assert ok is False
    assert reason == ReasonCode.FEES_BELOW_MIN


def test_alert_requires_score_and_buyers_after_eligibility():
    d = evaluate_admission(**_base())
    assert d.eligible is True
    assert can_alert(d, score=40, meaningful_buyers=10)[0] is False
    assert can_alert(d, score=80, meaningful_buyers=1)[0] is False
    assert can_alert(d, score=80, meaningful_buyers=3)[0] is True


def test_evaluate_market_dict_api():
    d = evaluate_market(_base())
    assert d.eligible is True
    assert isinstance(d.failed_filters, list)
    assert isinstance(d.passed_filters, list)
    assert isinstance(d.normalized_metrics, dict)
    assert isinstance(d.source_metadata, dict)
    assert d.reason_codes == []
    assert d.filter_version == FILTER_VERSION
    assert DEFAULT_MIN_GLOBAL_FEES_SOL == 1.0


def test_not_migrated_reject():
    d = evaluate_admission(**_base(migrated=False, tab="new"))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.NOT_MIGRATED


def test_unknown_migrated_fail_closed():
    d = evaluate_admission(**_base(migrated=None, tab=None))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.NOT_MIGRATED


def test_collects_all_failures():
    d = evaluate_admission(
        **_base(
            global_fees_sol=0.2,
            liquidity_usd=1.0,
            volume_usd=10.0,
            market_cap_usd=100.0,
            twitter=None,
            website=None,
            telegram=None,
            tiktok=None,
            socials=None,
        )
    )
    assert d.eligible is False
    assert ReasonCode.FEES_BELOW_MIN in d.reason_codes
    assert ReasonCode.LIQUIDITY_BELOW_MIN in d.reason_codes
    assert ReasonCode.VOLUME_BELOW_MIN in d.reason_codes
    assert ReasonCode.MARKET_CAP_BELOW_MIN in d.reason_codes
    assert ReasonCode.NO_SOCIAL in d.reason_codes


def test_observability_counts():
    filter_stats.reset()
    evaluate_admission(**_base(global_fees_sol=0.5))
    evaluate_admission(**_base())
    snap = filter_stats.snapshot()
    assert snap["markets_seen"] == 2
    assert snap["markets_rejected"] == 1
    assert snap["markets_eligible"] == 1
    assert snap["fee_below_min_count"] >= 1


def test_outcome_unknown_when_incomplete():
    o = label_outcome(peak_multiple=4.0, observation_complete=False)
    assert o.label == UNKNOWN


def test_outcome_runner_held_fade():
    assert label_outcome(peak_multiple=2.5, observation_complete=True).label == RUNNER
    assert label_outcome(peak_multiple=1.1, drawdown=0.1, observation_complete=True).label == HELD
    assert label_outcome(peak_multiple=1.1, drawdown=0.8, observation_complete=True).label == FADE


def test_pool_wallet_excluded():
    assert is_rankable_wallet("11111111111111111111111111111111") is False
    assert is_rankable_wallet("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA") is False
    assert is_rankable_wallet("HumanWallet1111111111111111111111111111111") is True


def test_backtest_uses_canonical_filter_and_alert_gate():
    markets = [
        _base(stinky_score=80, meaningful_buyer_count=5, observation_complete=True, peak_multiple=3.0),
        _base(global_fees_sol=0.4, stinky_score=99, meaningful_buyer_count=20),
        _base(stinky_score=10, meaningful_buyer_count=5),
    ]
    result = backtest_candidates(markets)
    assert result["unique_mints"] == 1  # same mint
    # only first unique mint kept (passing)
    item = result["items"][0]
    assert item["eligible"] is True
    assert item["alert_ok"] is True
    assert item["outcome"]["label"] == RUNNER
