"""Fee resolver + canonical gate integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stinky_core.admission import ReasonCode, evaluate_market
from stinky_core.fees import (
    DEFAULT_PASS_THRESHOLD_SOL,
    RESOLVER_VERSION,
    FeeResolver,
    FeeStatus,
    cache_clear,
    coerce_fees_verified,
    extract_explicit_api_fees,
    is_fresh,
    mark_stale,
    parse_explicit_fee_number,
    parse_tx_protocol_fees,
    unknown_observation,
    verified_observation,
)

MINT = "AbCdEf1234567890AbCdEf1234567890pump"
FIXTURE = Path(__file__).parent / "fixtures" / "pump_amm_fee_tx.json"


def _base_market(**kw):
    d = dict(
        mint=MINT,
        protocol="pumpswap",
        liquidity_usd=50.0,
        volume_usd=150_000.0,
        market_cap_usd=50_000.0,
        twitter="https://x.com/abc",
        migrated=True,
        tab="migrated",
    )
    d.update(kw)
    return d


def _admit(obs, **extra):
    fields = obs.as_admission_fields()
    return evaluate_market(_base_market(**fields, **extra))


def test_resolver_version():
    assert RESOLVER_VERSION == "fee-resolver-v1.0.0"


def test_verified_0_reject():
    obs = verified_observation(MINT, 0.00, protocol="pump", source="fixture", confidence=1.0)
    d = _admit(obs)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_verified_050_reject():
    obs = verified_observation(MINT, 0.50, protocol="pump", source="fixture", confidence=1.0)
    d = _admit(obs)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_verified_099_reject():
    obs = verified_observation(MINT, 0.99, protocol="pump", source="fixture", confidence=1.0)
    d = _admit(obs)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_BELOW_MIN


def test_verified_100_pass_fee_condition():
    obs = verified_observation(MINT, 1.00, protocol="pump", source="fixture", confidence=1.0)
    d = _admit(obs)
    assert d.rejection_reason != ReasonCode.FEES_BELOW_MIN
    assert d.rejection_reason != ReasonCode.FEES_UNKNOWN
    assert any(f["name"] == "global_fees" and f["passed"] for f in d.passed_filters)


def test_verified_300_pass_fee_condition():
    obs = verified_observation(MINT, 3.00, protocol="pump", source="onchain.pump.fee_recipient", confidence=1.0)
    d = _admit(obs)
    assert d.eligible is True


def test_unknown_fees_reject():
    obs = unknown_observation(MINT, protocol="pump", error="NO_TRADES")
    d = _admit(obs)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN
    assert d.metrics["fees_verified"] is False


def test_stale_fees_reject():
    fresh = verified_observation(MINT, 4.0, protocol="pump", source="fixture", confidence=1.0)
    stale = mark_stale(fresh)
    assert stale.fees_status == FeeStatus.STALE
    assert stale.fees_verified is False
    d = _admit(stale)
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_freshness_window():
    obs = verified_observation(MINT, 2.0, protocol="pump", source="fixture", confidence=1.0)
    assert is_fresh(obs, max_age_sec=300) is True
    old = verified_observation(MINT, 2.0, protocol="pump", source="fixture", confidence=1.0)
    object.__setattr__(
        old,
        "fees_observed_at",
        (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    )
    assert is_fresh(old, max_age_sec=300) is False


def test_malformed_fee_response_reject():
    assert parse_explicit_fee_number("not-a-number") is None
    assert parse_explicit_fee_number({"x": 1}) is None
    val, key, _raw = extract_explicit_api_fees({"fees_sol": "abc"})
    assert val is None and key is None
    d = evaluate_market(
        _base_market(global_fees_sol="nope", global_fees_verified=True)
    )
    assert d.eligible is False
    assert d.rejection_reason in (ReasonCode.FEES_UNKNOWN, ReasonCode.INVALID_MARKET_DATA)


def test_negative_fee_reject():
    assert parse_explicit_fee_number(-1.0) is None
    d = evaluate_market(_base_market(global_fees_sol=-1.0, global_fees_verified=True))
    assert d.eligible is False


def test_non_finite_fee_reject():
    assert parse_explicit_fee_number(float("nan")) is None
    assert parse_explicit_fee_number(float("inf")) is None
    assert parse_explicit_fee_number(float("-inf")) is None
    d = evaluate_market(_base_market(global_fees_sol=float("nan"), global_fees_verified=True))
    assert d.eligible is False
    d2 = evaluate_market(_base_market(global_fees_sol=float("inf"), global_fees_verified=True))
    assert d2.eligible is False


def test_duplicate_fee_observations_deterministic():
    tx = json.loads(FIXTURE.read_text())
    a = parse_tx_protocol_fees(tx)
    b = parse_tx_protocol_fees(tx)
    assert a == b
    assert abs(a - 0.000470626) < 1e-9


def test_cache_same_token_repeated():
    cache_clear()
    calls = {"n": 0}

    def http_get(url: str):
        calls["n"] += 1
        if "frontend-api" in url:
            return {"mint": MINT}
        if "trades" in url:
            return {"trades": [], "pagination": {"hasMore": False}}
        return {}

    r = FeeResolver(http_get=http_get, rpc_call=lambda m, p: None)
    x = r.resolve(MINT, protocol="pumpswap")
    y = r.resolve(MINT, protocol="pumpswap")
    assert x.fees_status == y.fees_status == FeeStatus.UNKNOWN
    assert calls["n"] == 2  # coin + trades once; second resolve is cache


def test_protocol_specific_pump_family_uses_onchain_parser():
    tx = json.loads(FIXTURE.read_text())
    assert parse_tx_protocol_fees(tx) > 0


def test_unsupported_protocol_unknown():
    cache_clear()
    r = FeeResolver(
        http_get=lambda url: {"mint": MINT} if "frontend-api" in url else {"trades": []},
        rpc_call=lambda m, p: None,
    )
    obs = r.resolve(MINT, protocol="raydium")
    assert obs.fees_verified is False
    assert obs.fees_error == "NO_FEE_MECHANISM"
    d = _admit(obs, protocol="raydium")
    assert d.eligible is False


def test_canonical_admission_is_only_gate():
    obs = verified_observation(MINT, 3.0, protocol="pump", source="fixture", confidence=1.0)
    d = _admit(obs)
    assert d.filter_version == "axiom-parity-v1.0.0"
    # score cannot be passed into admission
    d2 = evaluate_market(
        _base_market(
            global_fees_sol=0.2,
            global_fees_verified=True,
            stinky_score=99,
        )
    )
    assert d2.eligible is False


def test_creator_fees_field_is_not_global_fees():
    val, key, _ = extract_explicit_api_fees({"creator_fees_sol": 12.0, "name": "x"})
    assert val is None
    assert key is None


def test_explicit_total_fees_used():
    val, key, raw = extract_explicit_api_fees({"total_fees_sol": 4.2})
    assert val == 4.2 and key == "total_fees_sol" and raw == 4.2


def test_onchain_early_exit_when_lower_bound_ge_one():
    cache_clear()
    tx = json.loads(FIXTURE.read_text())
    # Scale WSOL deltas so one tx already exceeds 1 SOL.
    for b in tx["meta"]["postTokenBalances"]:
        b["uiTokenAmount"]["uiAmount"] = 3.0
    for b in tx["meta"]["preTokenBalances"]:
        b["uiTokenAmount"]["uiAmount"] = 1.0
    # two recipients * 2 SOL = 4 SOL

    def http_get(url: str):
        if "frontend-api" in url:
            return {"mint": MINT, "name": "x"}
        if "trades" in url:
            return {
                "trades": [{"tx": "SigBig1", "amountSol": "50", "type": "buy"}],
                "pagination": {"hasMore": True, "nextCursor": "x"},
            }
        return {}

    def rpc_call(method: str, params: list):
        assert method == "getTransaction"
        return tx

    r = FeeResolver(http_get=http_get, rpc_call=rpc_call, max_txs=10)
    obs = r.resolve(MINT, protocol="pumpswap")
    assert obs.fees_verified is True
    assert obs.fees_status == FeeStatus.VERIFIED
    assert obs.lower_bound is True
    assert obs.global_fees_sol is not None and obs.global_fees_sol + 1e-9 >= DEFAULT_PASS_THRESHOLD_SOL
    d = _admit(obs)
    assert d.eligible is True


def test_volume_is_not_a_fee_substitute():
    d = evaluate_market(
        _base_market(
            global_fees_sol=None,
            global_fees_verified=None,
            volume_usd=5_000_000,
            liquidity_usd=1_000_000,
            market_cap_usd=2_000_000,
        )
    )
    assert d.eligible is False
    assert d.rejection_reason == ReasonCode.FEES_UNKNOWN


def test_native_and_wsol_not_double_counted():
    tx = {
        "transaction": {
            "message": {
                "accountKeys": ["5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6"]
            }
        },
        "meta": {
            "err": None,
            "preBalances": [1_000_000_000],
            "postBalances": [1_000_000_000 + 500_000_000],  # +0.5 SOL native
            "preTokenBalances": [
                {
                    "owner": "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6",
                    "mint": "So11111111111111111111111111111111111111112",
                    "uiTokenAmount": {"uiAmount": 0.0},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6",
                    "mint": "So11111111111111111111111111111111111111112",
                    "uiTokenAmount": {"uiAmount": 0.5},
                }
            ],
        },
    }
    # same 0.5 wrapped and native → count once
    assert abs(parse_tx_protocol_fees(tx) - 0.5) < 1e-9


def test_coerce_fees_verified_never_infers_from_number():
    assert coerce_fees_verified(True) is True
    assert coerce_fees_verified(False) is False
    assert coerce_fees_verified("true") is True
    assert coerce_fees_verified("false") is False
    assert coerce_fees_verified(3.42) is None
    assert coerce_fees_verified(1) is None
    assert coerce_fees_verified(0) is None
    assert coerce_fees_verified(None) is None
    assert coerce_fees_verified("yes") is None


def test_unverified_observation_nulls_admission_fees():
    obs = unknown_observation(MINT, error="INCOMPLETE_OR_BELOW_THRESHOLD")
    fields = obs.as_admission_fields()
    assert fields["global_fees_sol"] is None
    assert fields["global_fees_verified"] is False


def test_stale_observation_does_not_pass_as_verified():
    obs = mark_stale(verified_observation(MINT, 9.0, protocol="pump", source="x", confidence=1.0))
    fields = obs.as_admission_fields()
    assert fields["global_fees_verified"] is False
    assert fields["global_fees_sol"] is None


def test_meme_payload_without_explicit_fee_key_is_not_fees():
    val, key, _ = extract_explicit_api_fees(
        {"volume": 1_000_000, "liquidity": 50_000, "market_cap": 80_000, "v": 12}
    )
    assert val is None and key is None

