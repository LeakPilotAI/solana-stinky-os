from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio
import json

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


def test_observation_path_validates_before_rpc_or_database(monkeypatch):
    touched = []

    def forbidden_observers(*args, **kwargs):
        touched.append("rpc")
        raise AssertionError("RPC observer construction must not occur before validation")

    def forbidden_session(*args, **kwargs):
        touched.append("db")
        raise AssertionError("database session must not open before validation")

    monkeypatch.setattr(cli, "build_cli_observers", forbidden_observers)
    monkeypatch.setattr(cli, "SessionLocal", forbidden_session)

    invalid = payload().model_copy(update={"chain_id": 1})
    with pytest.raises(ValueError, match="chain_id mismatch"):
        asyncio.run(cli.execute_operator_payload(invalid, rpc_env_vars=("GENESIS_RPC_A", "GENESIS_RPC_B")))

    assert touched == []


def test_provider_pre_attestation_rejects_one_bad_provider_before_database(monkeypatch):
    events = []

    class FakeObserver:
        def __init__(self, name, *, fail=False):
            self.name = name
            self.fail = fail
            self.rpc_url = f"https://{name}.example"
            self.chain = SimpleNamespace(key="base", chain_id=8453)

        def attest_chain(self):
            events.append(f"attest:{self.name}")
            if self.fail:
                raise cli.EvmRpcError(f"chain ID mismatch for {self.name}")
            return 8453

    observers = (
        FakeObserver("rpc-a"),
        FakeObserver("rpc-b", fail=True),
        FakeObserver("rpc-c"),
    )

    monkeypatch.setattr(cli, "build_cli_observers", lambda *args, **kwargs: observers)

    def forbidden_session():
        events.append("session")
        raise AssertionError("database session must not open after provider attestation failure")

    async def forbidden_invoke(*args, **kwargs):
        events.append("invoke")
        raise AssertionError("durable observation must not run after provider attestation failure")

    monkeypatch.setattr(cli, "SessionLocal", forbidden_session)
    monkeypatch.setattr(cli, "invoke_reference_dex_observation", forbidden_invoke)

    with pytest.raises(cli.EvmRpcError, match="chain ID mismatch"):
        asyncio.run(
            cli.execute_operator_payload(
                payload(),
                rpc_env_vars=("GENESIS_RPC_A", "GENESIS_RPC_B", "GENESIS_RPC_C"),
            )
        )

    assert events == ["attest:rpc-a", "attest:rpc-b"]


@pytest.mark.parametrize("malformed", ["0x02105", "0x21_05", "0x2105 "])
def test_real_rpc_malformed_chain_quantity_aborts_before_database(monkeypatch, malformed):
    calls = []
    def observer(name, result):
        def transport(url, body, timeout):
            request = json.loads(body)
            calls.append((name, request["method"]))
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}
        rpc = cli.EvmReadOnlyRpc("base", transport=transport)
        rpc.rpc_url = f"https://{name}.example"
        return rpc
    observers = (observer("a", "0x2105"), observer("b", malformed), observer("c", "0x2105"))
    monkeypatch.setattr(cli, "build_cli_observers", lambda *args: observers)
    def forbidden(*args, **kwargs):
        pytest.fail("malformed provider evidence reached database or audit")
    monkeypatch.setattr(cli, "SessionLocal", forbidden)
    monkeypatch.setattr(cli, "append_provider_attestation_audit", forbidden)
    with pytest.raises(cli.EvmRpcError, match="invalid chain id response"):
        asyncio.run(cli.execute_operator_payload(payload(), rpc_env_vars=("RPC_A", "RPC_B", "RPC_C")))
    assert calls == [("a", "eth_chainId"), ("b", "eth_chainId")]


@pytest.mark.parametrize("malformed", ["boolean_id", "both_members", "missing_id"])
def test_real_rpc_malformed_envelope_aborts_before_database(monkeypatch, malformed):
    calls = []
    def observer(name):
        def transport(url, body, timeout):
            request = json.loads(body)
            calls.append(name)
            response = {"jsonrpc": "2.0", "id": request["id"], "result": "0x2105"}
            if name == "b":
                if malformed == "boolean_id":
                    response["id"] = True
                elif malformed == "both_members":
                    response["error"] = None
                else:
                    del response["id"]
            return response
        rpc = cli.EvmReadOnlyRpc("base", transport=transport)
        rpc.rpc_url = f"https://{name}.example"
        return rpc
    observers = tuple(observer(name) for name in ("a", "b", "c"))
    monkeypatch.setattr(cli, "build_cli_observers", lambda *args: observers)
    def forbidden(*args, **kwargs):
        pytest.fail("malformed response envelope reached database or audit")
    monkeypatch.setattr(cli, "SessionLocal", forbidden)
    monkeypatch.setattr(cli, "append_provider_attestation_audit", forbidden)
    with pytest.raises(cli.EvmRpcError):
        asyncio.run(cli.execute_operator_payload(payload(), rpc_env_vars=("RPC_A", "RPC_B", "RPC_C")))
    assert calls == ["a", "b"]


def test_attestation_receipt_is_redacted_immutable_and_deterministic():
    class FakeObserver:
        def __init__(self, name, secret):
            self.rpc_url = f"https://{name}.example/rpc?api_key={secret}"
            self.chain = SimpleNamespace(key="base", chain_id=8453)

        def attest_chain(self):
            return 8453

    observers = (
        FakeObserver("rpc-b", "SECRET_B"),
        FakeObserver("rpc-a", "SECRET_A"),
    )
    receipt = cli.attest_cli_observers(observers)

    assert isinstance(receipt, tuple)
    assert tuple(row.provider for row in receipt) == tuple(sorted(row.provider for row in receipt))
    assert len(receipt) == len(observers)
    assert all(row.chain == "base" for row in receipt)
    assert all(row.chain_id == 8453 for row in receipt)
    assert all(row.attested is True for row in receipt)

    serialized = json.dumps([cli.asdict(row) for row in receipt], sort_keys=True)
    assert "SECRET_A" not in serialized
    assert "SECRET_B" not in serialized
    assert "api_key" not in serialized
    assert "https://" not in serialized

    with pytest.raises(Exception):
        receipt[0].chain_id = 1


def test_all_providers_attest_before_database_and_existing_path_continues(monkeypatch):
    events = []

    class FakeObserver:
        def __init__(self, name):
            self.name = name
            self.rpc_url = f"https://{name}.example"
            self.chain = SimpleNamespace(key="base", chain_id=8453)

        def attest_chain(self):
            events.append(f"attest:{self.name}")
            return 8453

    observers = tuple(FakeObserver(name) for name in ("rpc-a", "rpc-b", "rpc-c"))
    monkeypatch.setattr(cli, "build_cli_observers", lambda *args, **kwargs: observers)

    class FakeSession:
        async def __aenter__(self):
            events.append("session-enter")
            return self

        async def __aexit__(self, exc_type, exc, tb):
            events.append("session-exit")

        async def commit(self):
            events.append("commit")

        async def rollback(self):
            events.append("rollback")

    def fake_session_local():
        events.append("session-create")
        return FakeSession()

    observed_at = datetime(2026, 9, 14, 4, 20, tzinfo=timezone.utc)
    completed_at = datetime(2026, 9, 14, 4, 21, tzinfo=timezone.utc)

    async def fake_invoke(session, *, schedule, request, now):
        events.append("invoke")
        assert request.observers is observers
        assert request.min_quorum == 2
        return SimpleNamespace(
            trigger=SimpleNamespace(
                triggered=True,
                reason="OPERATOR_TRIGGERED_REFERENCE_DEX_OBSERVATION",
                observed_at=observed_at,
                run=object(),
            ),
            state=SimpleNamespace(
                chain="base",
                pool_address=payload().pool_address,
                last_completed_block=payload().block_number,
                last_completed_at=completed_at,
            ),
        )

    monkeypatch.setattr(cli, "SessionLocal", fake_session_local)
    monkeypatch.setattr(cli, "invoke_reference_dex_observation", fake_invoke)

    async def fake_append(session, record):
        events.append("audit")
        assert record.completed_at == completed_at
        assert record.block_number == payload().block_number
        assert record.provider_count == len(observers)
        assert tuple(row.provider for row in record.provider_attestations) == tuple(sorted(
            cli.provider_fingerprint(observer.rpc_url) for observer in observers
        ))

    monkeypatch.setattr(cli, "append_provider_attestation_audit", fake_append)

    result = asyncio.run(
        cli.execute_operator_payload(
            payload(),
            rpc_env_vars=("GENESIS_RPC_A", "GENESIS_RPC_B", "GENESIS_RPC_C"),
        )
    )

    assert events == [
        "attest:rpc-a",
        "attest:rpc-b",
        "attest:rpc-c",
        "session-create",
        "session-enter",
        "invoke",
        "audit",
        "commit",
        "session-exit",
    ]
    assert result["triggered"] is True
    assert result["read_only"] is True
    assert result["execution_authorized"] is False
    assert result["state"]["last_completed_block"] == payload().block_number
    assert len(result["provider_attestations"]) == len(observers)
    assert all(row["attested"] is True for row in result["provider_attestations"])
    assert all(row["chain"] == "base" for row in result["provider_attestations"])
    assert all(row["chain_id"] == 8453 for row in result["provider_attestations"])
    assert [row["provider"] for row in result["provider_attestations"]] == sorted(
        row["provider"] for row in result["provider_attestations"]
    )


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
