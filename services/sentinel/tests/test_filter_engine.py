"""Mandatory admission tests for StinkyFilterEngine (axiom-parity-v1.0.0).

Invariant: no token with global_fees_sol < 1.0 (or unverified/missing fees)
can be accepted. Score cannot override a failed hard filter.
"""

from __future__ import annotations

import pytest

from sentinel.filter_engine import (
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    FILTER_VERSION,
    FilterConfig,
    StinkyFilterEngine,
    evaluate_admission,
)


def _engine(**kw) -> StinkyFilterEngine:
    return StinkyFilterEngine(FilterConfig(**kw) if kw else FilterConfig())


def _base(**overrides):
    """Passing baseline — mutate per case."""
    d = {
        "mint": "AbCdEf1234567890pump",
        "protocol": "pumpfun",
        "global_fees_sol": 6.0,
        "global_fees_verified": True,
        "global_fees_source": "pump.fun/total_fees",
        "liquidity_usd": 50.0,
        "volume_usd": 150_000.0,
        "market_cap_usd": 50_000.0,
        "twitter": "https://x.com/someproject",
    }
    d.update(overrides)
    return d


# --- CASE 1–7: fees ---


def test_case1_fees_zero_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.0))
    assert d.accepted is False
    assert d.rejection_reason == "GLOBAL_FEES_BELOW_MINIMUM"


def test_case2_fees_half_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.5))
    assert d.accepted is False
    assert d.rejection_reason == "GLOBAL_FEES_BELOW_MINIMUM"


def test_case3_fees_point99_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.99))
    assert d.accepted is False
    assert d.rejection_reason == "GLOBAL_FEES_BELOW_MINIMUM"


def test_case4_fees_five_pass_fees_gate():
    d = evaluate_admission(**_base(global_fees_sol=5.0))
    assert d.accepted is True
    assert d.rejection_reason is None
    assert any(f["name"] == "global_fees" for f in d.passed_filters)


def test_case5_fees_missing_reject():
    d = evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None))
    assert d.accepted is False
    assert d.rejection_reason in (
        "GLOBAL_FEES_UNKNOWN",
        "GLOBAL_FEES_UNVERIFIED",
        "GLOBAL_FEES_INVALID",
    )


def test_case6_fees_malformed_reject():
    d = evaluate_admission(**_base(global_fees_sol="not-a-number", global_fees_verified=True))  # type: ignore[arg-type]
    assert d.accepted is False


def test_case7_fees_negative_reject():
    d = evaluate_admission(**_base(global_fees_sol=-1.0, global_fees_verified=True))
    assert d.accepted is False


def test_fees_unverified_even_with_number_reject():
    d = evaluate_admission(**_base(global_fees_sol=10.0, global_fees_verified=False))
    assert d.accepted is False
    assert d.rejection_reason == "GLOBAL_FEES_UNVERIFIED"


def test_fees_verified_none_with_number_reject():
    """Missing verification flag must not pass."""
    d = evaluate_admission(**_base(global_fees_sol=10.0, global_fees_verified=None))
    assert d.accepted is False
    assert d.rejection_reason == "GLOBAL_FEES_UNVERIFIED"


# --- CASE 8–9: other hard gates ---


def test_case8_fees_ok_liquidity_low_reject():
    d = evaluate_admission(**_base(global_fees_sol=10.0, liquidity_usd=7.0))
    assert d.accepted is False
    assert d.rejection_reason == "LIQUIDITY_BELOW_MINIMUM"


def test_case9_full_baseline_pass():
    d = evaluate_admission(**_base())
    assert d.accepted is True
    assert d.filter_version == FILTER_VERSION
    assert d.rejection_reason is None


# --- CASE 10: score cannot override (engine has no score input) ---


def test_case10_low_fees_high_score_irrelevant():
    """FilterEngine does not accept score; low fees always reject."""
    d = evaluate_admission(**_base(global_fees_sol=0.1))
    assert d.accepted is False
    assert "score" not in d.metrics
    assert d.rejection_reason == "GLOBAL_FEES_BELOW_MINIMUM"


# --- CASE 11: social ---


def test_case11_social_missing_reject():
    d = evaluate_admission(
        **_base(twitter=None, website=None, telegram=None, tiktok=None, socials=None)
    )
    assert d.accepted is False
    assert d.rejection_reason == "SOCIAL_REQUIREMENT_FAILED"


def test_social_placeholder_reject():
    d = evaluate_admission(**_base(twitter="https://", website=None))
    assert d.accepted is False
    assert d.rejection_reason == "SOCIAL_REQUIREMENT_FAILED"


# --- CASE 12: protocol ---


def test_case12_unknown_protocol_reject():
    d = evaluate_admission(**_base(protocol="unknown-dex-xyz", dex_id=None))
    assert d.accepted is False
    assert d.rejection_reason in ("PROTOCOL_NOT_ALLOWED", "UNKNOWN_PROTOCOL")


def test_raydium_denied():
    d = evaluate_admission(**_base(protocol="raydium"))
    assert d.accepted is False
    assert d.rejection_reason == "PROTOCOL_NOT_ALLOWED"


def test_meteora_denied():
    d = evaluate_admission(**_base(protocol="meteoraAmmV2"))
    assert d.accepted is False


def test_volume_below_reject():
    d = evaluate_admission(**_base(volume_usd=50_000))
    assert d.accepted is False
    assert d.rejection_reason == "VOLUME_BELOW_MINIMUM"


def test_mcap_below_reject():
    d = evaluate_admission(**_base(market_cap_usd=10_000))
    assert d.accepted is False
    assert d.rejection_reason == "MARKET_CAP_BELOW_MINIMUM"


def test_missing_liquidity_reject():
    d = evaluate_admission(**_base(liquidity_usd=None))
    assert d.accepted is False
    assert d.rejection_reason == "LIQUIDITY_UNKNOWN"


def test_missing_volume_reject():
    d = evaluate_admission(**_base(volume_usd=None))
    assert d.accepted is False
    assert d.rejection_reason == "VOLUME_UNKNOWN"


def test_invariant_no_sub_five_sol_accepted():
    """Formal invariant: accepted must be 0 for fees < 5."""
    for fee in (0.0, 0.01, 0.1, 0.5, 0.99, 1.0, 3.0, 4.99):
        d = evaluate_admission(**_base(global_fees_sol=fee))
        assert d.accepted is False, f"fees={fee} must reject"



def test_default_min_fees_is_five():
    assert DEFAULT_MIN_GLOBAL_FEES_SOL == 5.0


def test_decision_serializable():
    d = evaluate_admission(**_base())
    payload = d.to_dict()
    assert payload["accepted"] is True
    assert payload["filter_version"] == FILTER_VERSION
    assert "failed_filters" in payload
    assert "passed_filters" in payload
