"""Gate 1 tests for StinkyFilterEngine (volume-first-v1.0.0)."""

from __future__ import annotations

from sentinel.filter_engine import (
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    FILTER_VERSION,
    GATE1_VOLUME_5M_USD,
    FilterConfig,
    ReasonCode,
    StinkyFilterEngine,
    evaluate_admission,
    evaluate_gate1,
)


def _engine(**kw) -> StinkyFilterEngine:
    return StinkyFilterEngine(FilterConfig(**kw) if kw else FilterConfig())


def _base(**overrides):
    d = {
        "mint": "AbCdEf1234567890AbCdEf1234567890pump",
        "protocol": "pumpfun",
        "global_fees_sol": None,
        "global_fees_verified": None,
        "liquidity_usd": 50.0,
        "volume_usd": 33_000.0,
        "market_cap_usd": 50_000.0,
        "twitter": "https://x.com/someproject",
        "migrated": True,
        "tab": "migrated",
    }
    d.update(overrides)
    return d


def test_gate1_volume_149999_reject():
    d = evaluate_gate1(_base(volume_usd=32_999))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_gate1_volume_33000_pass():
    d = evaluate_gate1(_base(volume_usd=33_000))
    assert d.accepted is True
    assert d.eligible is True


def test_gate1_volume_200000_pass():
    d = evaluate_gate1(_base(volume_usd=200_000))
    assert d.accepted is True


def test_unknown_fees_do_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=None, global_fees_verified=None))
    assert d.accepted is True
    assert ReasonCode.FEES_UNKNOWN not in d.reason_codes


def test_verified_fees_below_one_are_evidence_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.0, global_fees_verified=True))
    assert d.accepted is True
    assert d.metrics.get("fee_signal") == "negative"


def test_fees_half_evidence_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.5, global_fees_verified=True))
    assert d.accepted is True
    assert d.metrics.get("fee_signal") == "negative"


def test_fees_point99_evidence_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=0.99, global_fees_verified=True))
    assert d.accepted is True


def test_fees_one_positive_evidence():
    d = evaluate_admission(**_base(global_fees_sol=1.0, global_fees_verified=True))
    assert d.accepted is True
    assert d.metrics.get("fee_signal") == "positive"
    assert any(f["name"] == "global_fees" for f in d.passed_filters)


def test_fees_malformed_does_not_reject_gate1():
    d = evaluate_admission(**_base(global_fees_sol="not-a-number", global_fees_verified=True))  # type: ignore[arg-type]
    assert d.accepted is True
    assert d.metrics.get("fee_signal") == "unavailable"


def test_unverified_fees_do_not_reject():
    d = evaluate_admission(**_base(global_fees_sol=10.0, global_fees_verified=False))
    assert d.accepted is True
    assert ReasonCode.FEES_UNKNOWN not in d.reason_codes


def test_score_cannot_override_volume_gate():
    d = evaluate_admission(**_base(volume_usd=1_000))
    assert d.accepted is False
    assert "score" not in d.metrics
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_volume_32999_reject():
    d = evaluate_admission(**_base(volume_usd=32_999))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_volume_32999_below_gate1():
    d = evaluate_admission(**_base(volume_usd=32_999))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_BELOW_MIN


def test_liquidity_and_social_not_required():
    d = evaluate_admission(
        **_base(
            liquidity_usd=1.0,
            market_cap_usd=1.0,
            twitter=None,
            website=None,
            telegram=None,
            tiktok=None,
            socials=None,
        )
    )
    assert d.accepted is True


def test_missing_volume_reject():
    d = evaluate_admission(**_base(volume_usd=None))
    assert d.accepted is False
    assert d.rejection_reason == ReasonCode.VOLUME_UNKNOWN


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


def test_optional_fees_floor_still_one():
    assert DEFAULT_MIN_GLOBAL_FEES_SOL == 1.0
    assert _engine().config.min_global_fees_sol == 1.0
    assert GATE1_VOLUME_5M_USD == 33_000.0


def test_filter_version():
    d = evaluate_admission(**_base())
    assert d.filter_version == FILTER_VERSION == "volume-first-v1.0.0"


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
