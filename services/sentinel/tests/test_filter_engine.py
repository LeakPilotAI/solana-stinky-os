"""Mandatory admission tests for StinkyFilterEngine (axiom-parity-v1.0.0)."""

from __future__ import annotations

from sentinel.filter_engine import (
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    FILTER_VERSION,
    FilterConfig,
    ReasonCode,
    StinkyFilterEngine,
    evaluate_admission,
)


def _engine(**kw) -> StinkyFilterEngine:
    return StinkyFilterEngine(FilterConfig(**kw) if kw else FilterConfig())


def _base(**overrides):
    d = {
        "mint": "AbCdEf1234567890AbCdEf1234567890pump",
        "protocol": "pumpfun",
        "global_fees_sol": 6.0,
        "global_fees_verified": True,
        "global_fees_source": "pump.fun/total_fees",
        "liquidity_usd": 50.0,
        "volume_usd": 150_000.0,
        "market_cap_usd": 50_000.0,
        "twitter": "https://x.com/someproject",
        "migrated": True,
        "tab": "migrated",
    }
    d.update(overrides)
    return d


def test_fees_zero_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.0))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_fees_half_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.5))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_fees_point99_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.99))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_fees_one_pass():
    d = evaluate_admission(**_base(global_fees_sol=1.0))
    assert d.accepted is True
    assert d.eligible is True
    assert d.rejection_reason is None
    assert any(f["name"] == "global_fees" for f in d.passed_filters)


def test_fees_two_pass():
    d = evaluate_admission(**_base(global_fees_sol=2.0))
    assert d.accepted is True


def test_fees_three_pass():
    d = evaluate_admission(**_base(global_fees_sol=3.0))
    assert d.accepted is True


def test_fees_missing_reject():
    d = evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_fees_malformed_reject():
    d = evaluate_admission(**_base(global_fees_sol="not-a-number", global_fees_verified=True))  # type: ignore[arg-type]
    assert d.accepted is False
    assert d.rejection_reason in (ReasonCode.FEES_UNKNOWN, ReasonCode.INVALID_MARKET_DATA)


def test_fees_negative_reject():
    d = evaluate_admission(**_base(global_fees_sol=-1.0, global_fees_verified=True))
    assert d.accepted is False


def test_fees_nan_reject():
    d = evaluate_admission(**_base(global_fees_sol=float("nan"), global_fees_verified=True))
    assert d.accepted is False


def test_fees_unverified_even_with_number_reject():
    d = evaluate_admission(**_base(global_fees_sol=10.0, global_fees_verified=False))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_fees_verified_none_with_number_reject():
    d = evaluate_admission(**_base(global_fees_sol=10.0, global_fees_verified=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_high_score_cannot_override_low_fees():
    d = evaluate_admission(**_base(global_fees_sol=0.42))
    assert d.accepted is False
    assert "score" not in d.metrics
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_volume_99999_reject():
    d = evaluate_admission(**_base(volume_usd=99_999))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_volume_100000_pass():
    d = evaluate_admission(**_base(volume_usd=100_000))
    assert d.accepted is True


def test_mcap_31332_reject():
    d = evaluate_admission(**_base(market_cap_usd=31_332))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.MARKET_CAP_BELOW_MIN


def test_mcap_31332_99_reject():
    d = evaluate_admission(**_base(market_cap_usd=31_332.99))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.MARKET_CAP_BELOW_MIN


def test_mcap_31333_pass():
    d = evaluate_admission(**_base(market_cap_usd=31_333))
    assert d.accepted is True


def test_liquidity_7_99_reject():
    d = evaluate_admission(**_base(liquidity_usd=7.99))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.LIQUIDITY_BELOW_MIN


def test_liquidity_8_pass():
    d = evaluate_admission(**_base(liquidity_usd=8.0))
    assert d.accepted is True


def test_missing_liquidity_reject():
    d = evaluate_admission(**_base(liquidity_usd=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.LIQUIDITY_UNKNOWN


def test_missing_volume_reject():
    d = evaluate_admission(**_base(volume_usd=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_UNKNOWN


def test_social_missing_reject():
    d = evaluate_admission(
        **_base(twitter=None, website=None, telegram=None, tiktok=None, socials=None)
    )
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.NO_SOCIAL


def test_social_placeholder_reject():
    d = evaluate_admission(**_base(twitter="https://", website=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.NO_SOCIAL


def test_unknown_protocol_reject():
    d = evaluate_admission(**_base(protocol="unknown-dex-xyz", dex_id=None))
    assert d.accepted is False
    assert d.rejection_reason in (ReasonCode.PROTOCOL_DISABLED, ReasonCode.PROTOCOL_UNKNOWN)


def test_empty_protocol_reject():
    d = evaluate_admission(**_base(protocol=None, dex_id=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.PROTOCOL_UNKNOWN


def test_raydium_denied():
    d = evaluate_admission(**_base(protocol="raydium"))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.PROTOCOL_DISABLED


def test_pumpamm_denied():
    d = evaluate_admission(**_base(protocol="pumpAmm"))
    assert d.accepted is False


def test_meteora_denied():
    d = evaluate_admission(**_base(protocol="meteoraAmmV2"))
    assert d.accepted is False


def test_orca_denied():
    d = evaluate_admission(**_base(protocol="orca"))
    assert d.accepted is False


def test_allowed_protocols_pass_gate():
    for proto in ("pump", "pumpfun", "pumpswap", "mayhem", "moonshot", "bonk", "bags"):
        d = evaluate_admission(**_base(protocol=proto))
        assert d.accepted is True, proto


def test_invariant_no_sub_one_sol_accepted():
    for fee in (0.0, 0.01, 0.1, 0.3, 0.5, 0.99):
        d = evaluate_admission(**_base(global_fees_sol=fee))
        assert d.accepted is False, f"fees={fee} must reject"


def test_default_min_fees_is_one():
    assert DEFAULT_MIN_GLOBAL_FEES_SOL == 1.0
    assert _engine().config.min_global_fees_sol == 1.0


def test_filter_version():
    d = evaluate_admission(**_base())
    assert d.filter_version == FILTER_VERSION == "axiom-parity-v1.0.0"


def test_decision_serializable():
    d = evaluate_admission(**_base())
    payload = d.to_dict()
    assert payload["accepted"] is True
    assert payload["eligible"] is True
    assert payload["filter_version"] == FILTER_VERSION
    assert "failed_filters" in payload
    assert "passed_filters" in payload
    assert "reason_codes" in payload
    assert "normalized_metrics" in payload
    assert "source_metadata" in payload


def test_stale_unverified_fees_reject():
    d = evaluate_admission(
        **_base(global_fees_sol=12.0, global_fees_verified=False, global_fees_source="stale-cache")
    )
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN
