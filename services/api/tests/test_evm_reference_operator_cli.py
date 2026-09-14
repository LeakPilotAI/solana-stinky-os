from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import stinky_api.evm_reference_operator_cli as cli
from stinky_api.evm_reference_operator_transport import (
    ReferenceDexOperatorPayload,
    ReferenceSourcePayload,
    build_operator_request,
    serialize_operator_result,
    validate_operator_payload,
)


def payload():
    return ReferenceDexOperatorPayload(
        chain="base",
        chain_id=8453,
        factory_address="0x8909dc15e40173ff4699343b6eb8132c65e18ec6",
        pool_address="0x1111111111111111111111111111111111111111",
        token0_address="0x2222222222222222222222222222222222222222",
        token1_address="0x3333333333333333333333333333333333333333",
        event_family="V2_STYLE_PAIR_CREATED",
        fee_tier=None,
        first_seen_block=100,
        block_hash="0x" + "11" * 32,
        transaction_hash="0x" + "22" * 32,
        log_index="0x1",
        router_address="0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        sources=(
            ReferenceSourcePayload(
                address="0x8909dc15e40173ff4699343b6eb8132c65e18ec6",
                contract_role="FACTORY",
                implementation_family="UNISWAP_V2",
                implementation_version="PINNED",
                source_repository="Uniswap/sdk-core",
                source_commit="baff6d3c78b09aa0b2f96148bc223b42a57fd28a",
                source_path="src/addresses.ts",
                source_locator="factory",
            ),
            ReferenceSourcePayload(
                address="0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
                contract_role="ROUTER",
                implementation_family="UNISWAP_V2",
                implementation_version="PINNED",
                source_repository="Uniswap/sdk-core",
                source_commit="baff6d3c78b09aa0b2f96148bc223b42a57fd28a",
                source_path="src/addresses.ts",
                source_locator="router",
            ),
        ),
        block_number=123456,
        min_quorum=2,
        interval_seconds=300,
        enabled=True,
    )


def test_transport_builds_existing_immutable_runtime_types():
    observers = (
        SimpleNamespace(rpc_url="https://rpc-a.example", chain=SimpleNamespace(key="base")),
        SimpleNamespace(rpc_url="https://rpc-b.example", chain=SimpleNamespace(key="base")),
    )
    schedule, request = build_operator_request(payload(), observers)
    assert schedule.interval_seconds == 300
    assert schedule.enabled is True
    assert request.observers is observers
    assert isinstance(request.sources, tuple)
    assert request.block_number == 123456
    assert request.min_quorum == 2
    assert request.pool.factory_address == payload().factory_address
    assert request.router_address == payload().router_address


def test_transport_fails_closed_without_quorum():
    with pytest.raises(ValueError, match="not enough preconfigured observers"):
        build_operator_request(payload(), (SimpleNamespace(rpc_url="https://rpc-a.example"),))


def test_offline_payload_preflight_is_audit_safe():
    result = validate_operator_payload(payload())
    assert result["validated_offline"] is True
    assert result["read_only"] is True
    assert result["execution_authorized"] is False
    assert result["chain"] == "base"
    assert result["chain_id"] == 8453
    assert result["source_count"] == 2


def test_offline_payload_preflight_fails_closed_on_bad_evidence():
    with pytest.raises(ValueError, match="chain_id mismatch"):
        validate_operator_payload(payload().model_copy(update={"chain_id": 1}))
    with pytest.raises(ValueError, match="32-byte hex"):
        validate_operator_payload(payload().model_copy(update={"block_hash": "0x1234"}))
    with pytest.raises(ValueError, match="canonical address"):
        validate_operator_payload(payload().model_copy(update={"pool_address": "<REPLACE_POOL_ADDRESS>"}))
    bad_source = payload().sources[0].model_copy(update={"source_repository": "<REPLACE_SOURCE_REPOSITORY>"})
    with pytest.raises(ValueError, match="unresolved operator template placeholder"):
        validate_operator_payload(payload().model_copy(update={"sources": (bad_source,)}))


def test_result_serialization_is_audit_safe_and_non_execution():
    observed_at = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 9, 14, 3, 1, tzinfo=timezone.utc)
    result = SimpleNamespace(
        trigger=SimpleNamespace(
            triggered=True,
            reason="OPERATOR_TRIGGERED_REFERENCE_DEX_OBSERVATION",
            observed_at=observed_at,
            run=object(),
        ),
        state=SimpleNamespace(
            chain="base",
            pool_address="0x1111111111111111111111111111111111111111",
            last_completed_block=123456,
            last_completed_at=completed_at,
        ),
    )
    serialized = serialize_operator_result(result)
    assert serialized["triggered"] is True
    assert serialized["read_only"] is True
    assert serialized["execution_authorized"] is False
    assert serialized["state"]["last_completed_block"] == 123456
    assert "run" not in serialized


def test_cli_observers_require_distinct_https_env_urls(monkeypatch):
    created = []

    class FakeRpc:
        def __init__(self, chain, *, transport):
            self.chain = SimpleNamespace(key=chain)
            self.rpc_url = "https://default.example"
            created.append((chain, transport))

    monkeypatch.setattr(cli, "EvmReadOnlyRpc", FakeRpc)
    monkeypatch.setenv("GENESIS_RPC_A", "https://rpc-a.example")
    monkeypatch.setenv("GENESIS_RPC_B", "https://rpc-b.example")
    observers = cli.build_cli_observers("base", ("GENESIS_RPC_A", "GENESIS_RPC_B"))
    assert tuple(observer.rpc_url for observer in observers) == (
        "https://rpc-a.example",
        "https://rpc-b.example",
    )
    assert len(created) == 2

    monkeypatch.setenv("GENESIS_RPC_B", "https://rpc-a.example")
    with pytest.raises(ValueError, match="distinct URLs"):
        cli.build_cli_observers("base", ("GENESIS_RPC_A", "GENESIS_RPC_B"))
