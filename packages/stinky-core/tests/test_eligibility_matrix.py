"""Gate 1 + pipeline matrix — volume-first-v1.0.0."""

from __future__ import annotations

from stinky_core.admission import (
    DEFAULT_MIN_VOLUME_USD,
    FILTER_VERSION,
    GATE1_VOLUME_5M_USD,
    LEGACY_FEE_GATE_CONFIG,
    ReasonCode,
    can_alert,
    evaluate_admission,
    evaluate_gate1,
    evaluate_market,
    filter_stats,
)
from stinky_core.backtest import backtest_candidates
from stinky_core.identity import UniqueMintIndex
from stinky_core.intelligence import investigate
from stinky_core.outcomes import FADE, HELD, RUNNER, UNKNOWN, label_outcome
from stinky_core.pools import is_rankable_wallet

MINT = "AbCdEf1234567890AbCdEf1234567890pump"


def _base(**kw):
    d = dict(
        mint=MINT,
        protocol="pumpfun",
        volume_usd=150_000.0,
        migrated=True,
        tab="migrated",
    )
    d.update(kw)
    return d


def _buyers(n=8, smart=4):
    buyers = [{"wallet": f"W{i:02d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "sol_spent": 0.2} for i in range(n)]
    perf = {
        b["wallet"]: {"early_buy_count": 5, "tokens_purchased": 5, "hit_rate": 0.62, "avg_return_pct": 40}
        for b in buyers[:smart]
    }
    return buyers, perf


def setup_function() -> None:
    filter_stats.reset()


def test_gate1_volume_149999_reject():
    d = evaluate_gate1(_base(volume_usd=149_999))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_gate1_volume_150000_pass():
    d = evaluate_gate1(_base(volume_usd=150_000))
    assert d.eligible is True
    assert d.filter_version == FILTER_VERSION
    assert GATE1_VOLUME_5M_USD == DEFAULT_MIN_VOLUME_USD == 150_000.0


def test_gate1_volume_200000_pass():
    d = evaluate_gate1(_base(volume_usd=200_000))
    assert d.eligible is True


def test_gate1_invalid_volume_reject():
    d = evaluate_gate1(_base(volume_usd="nope"))
    assert d.eligible is False
    assert d.rejection_reason in (ReasonCode.VOLUME_UNKNOWN, ReasonCode.INVALID_MARKET_DATA)


def test_gate1_missing_volume_reject():
    d = evaluate_gate1(_base(volume_usd=None))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.VOLUME_UNKNOWN


def test_gate1_negative_volume_reject():
    d = evaluate_gate1(_base(volume_usd=-1))
    assert d.eligible is False


def test_enabled_protocol_eligible():
    for proto in ("pump", "pumpfun", "pumpswap", "mayhem", "moonshot", "bonk", "bags"):
        assert evaluate_gate1(_base(protocol=proto)).eligible is True, proto


def test_disabled_protocol_reject():
    for proto in ("raydium", "pumpAmm", "meteoraAmmV2", "orca"):
        d = evaluate_gate1(_base(protocol=proto))
        assert d.eligible is False, proto
        assert d.rejection_reason == ReasonCode.PROTOCOL_DISABLED


def test_unknown_fees_do_not_reject_gate1():
    d = evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None))
    assert d.eligible is True
    assert ReasonCode.FEES_UNKNOWN not in d.reason_codes


def test_verified_fees_below_one_are_evidence_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.4, global_fees_verified=True))
    assert d.eligible is True
    assert d.metrics.get("fee_signal") == "negative"


def test_verified_fees_ge_one_positive_evidence():
    d = evaluate_admission(**_base(global_fees_sol=1.0, global_fees_verified=True))
    assert d.eligible is True
    assert d.metrics.get("fee_signal") == "positive"
    assert any(f["name"] == "global_fees" and f["passed"] for f in d.passed_filters)


def test_legacy_profile_still_requires_fees():
    d = evaluate_market(_base(global_fees_sol=None), config=LEGACY_FEE_GATE_CONFIG)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_liquidity_and_social_not_gate1():
    d = evaluate_admission(
        **_base(liquidity_usd=1.0, twitter=None, website=None, telegram=None, tiktok=None, socials=None)
    )
    assert d.eligible is True


def test_not_migrated_reject():
    d = evaluate_admission(**_base(migrated=False, tab="new"))
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.NOT_MIGRATED


def test_duplicate_mint_one_candidate():
    idx = UniqueMintIndex()
    assert idx.add(MINT) is True
    assert idx.add(MINT) is False
    result = backtest_candidates([_base(), _base(), _base(mint=MINT)])
    assert result["unique_mints"] == 1
    assert result["duplicate_mints_dropped"] == 2


def test_future_volume_cannot_pass_gate1():
    """peak_volume is future; Gate 1 uses decision-time volume_usd only."""
    row = _base(volume_usd=20_000, peak_volume=500_000, peak_multiple=4.0, observation_complete=True)
    d = evaluate_gate1(row)
    assert d.eligible is False
    result = backtest_candidates([row])
    assert result["gate1_passed"] == 0
    assert result["alerts"] == 0
    assert result["items"][0]["outcome"]["label"] == RUNNER  # outcome may use future, gate1 may not


def test_alert_cannot_bypass_gate1():
    d = evaluate_admission(**_base(volume_usd=1_000))
    ok, reason = can_alert(d, score=99, meaningful_buyers=20, inspection_complete=True, has_intelligence=True)
    assert d.eligible is False
    assert ok is False
    assert reason == ReasonCode.VOLUME_BELOW_MIN


def test_alert_requires_inspection():
    d = evaluate_admission(**_base())
    assert d.eligible is True
    assert can_alert(d, score=80, meaningful_buyers=8)[0] is False


def test_evaluate_market_dict_api():
    d = evaluate_market(_base())
    assert d.eligible is True
    assert d.filter_version == FILTER_VERSION
    assert d.reason_codes == []


def test_backtest_pipeline_counts():
    buyers, perf = _buyers()
    good = _base(
        buyers=buyers,
        wallet_performance=perf,
        unique_wallets=12,
        trade_count=40,
        top4_wallet_volume_share=0.3,
        observation_complete=True,
        peak_multiple=3.0,
        fee_status="UNKNOWN",
    )
    weak = _base(mint="OtherMint11111111111111111111111111111pump", volume_usd=10_000)
    result = backtest_candidates([good, weak])
    assert result["unique_candidates"] == 2
    assert result["gate1_passed"] == 1
    assert result["deep_inspected"] == 1
    assert result["engine"].startswith("stinky-backtest-v1.")


def test_outcome_labels():
    assert label_outcome(peak_multiple=4.0, observation_complete=False).label == UNKNOWN
    assert label_outcome(peak_multiple=2.5, observation_complete=True).label == RUNNER
    assert label_outcome(peak_multiple=1.1, drawdown=0.1, observation_complete=True).label == HELD
    assert label_outcome(peak_multiple=1.1, drawdown=0.8, observation_complete=True).label == FADE


def test_pool_wallet_excluded():
    assert is_rankable_wallet("11111111111111111111111111111111") is False
    assert is_rankable_wallet("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA") is False
    assert is_rankable_wallet("HumanWallet1111111111111111111111111111111") is True


def test_investigate_uses_only_provided_evidence():
    inv = investigate(_base())
    assert inv.complete is True
    assert inv.global_fees_sol is None
    assert inv.fee_status == "UNKNOWN"
