import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from stinky_api import evm_provider_attestation_audit as audit
from stinky_api import evm_reference_operator_cli as cli
from stinky_core.evm_consensus import provider_fingerprint
from test_evm_reference_operator_cli import payload


def record():
    return audit.ProviderAttestationAudit(
        chain="base", pool_address="0x" + "11" * 20, block_number=123456,
        completed_at=datetime(2026, 9, 14, tzinfo=timezone.utc), provider_count=2,
        provider_attestations=tuple(audit.ProviderAttestationReceipt(
            provider_fingerprint(f"https://rpc-{name}.example/private/SECRET?key=SECRET"), "base", 8453,
        ) for name in ("a", "b")),
    )


def test_codec_roundtrip_deterministic_and_redacted():
    original = record()
    encoded = audit.encode_provider_attestation_audit(original)
    assert audit.decode_provider_attestation_audit(encoded) == original
    assert json.dumps(encoded, sort_keys=True) == json.dumps(audit.encode_provider_attestation_audit(original), sort_keys=True)
    assert all(secret not in json.dumps(encoded) for secret in ("https://", "SECRET", "/private", "?key="))
    encoded["provider_attestations"][0]["attested"] = False
    assert original.provider_attestations[0].attested is True


@pytest.mark.parametrize("change", [
    {"provider_count": 3}, {"provider_count": True}, {"block_number": True},
    {"block_number": -1}, {"completed_at": datetime(2026, 9, 14)},
    {"pool_address": "not-an-address"}, {"pool_address": None}, {"chain": "solana"},
    {"chain": "not-a-chain"}, {"chain": None},
    {"provider_attestations": ()},
])
def test_invalid_record_rejected(change):
    with pytest.raises(ValueError):
        replace(record(), **change)


@pytest.mark.parametrize("change", [
    {"provider": "https://rpc.example/SECRET"}, {"chain": "ethereum"},
    {"chain_id": 1}, {"chain_id": True}, {"attested": False}, {"attested": 1},
])
def test_invalid_receipt_rejected(change):
    original = record()
    with pytest.raises(ValueError):
        replace(original, provider_attestations=(replace(original.provider_attestations[0], **change), original.provider_attestations[1]))


def test_duplicate_unsorted_and_mutable_receipts_rejected():
    original = record()
    for rows in (original.provider_attestations[::-1], (original.provider_attestations[0],) * 2, list(original.provider_attestations)):
        with pytest.raises(ValueError):
            replace(original, provider_attestations=rows)


@pytest.mark.parametrize("change", [
    {"version": 2}, {"version": True}, {"extra": "untrusted"},
    {"completed_at": "invalid"}, {"provider_attestations": {}},
    {"provider_attestations": [{"provider": "missing fields"}]},
])
def test_malformed_codec_rejected(change):
    encoded = audit.encode_provider_attestation_audit(record())
    encoded.update(change)
    with pytest.raises(ValueError):
        audit.decode_provider_attestation_audit(encoded)


def test_store_exact_readback_and_identity_validation():
    original = record()
    class Session:
        row = None
        async def execute(self, statement, params):
            if str(statement).lstrip().startswith("INSERT"):
                self.row = {key: params[key] for key in ("chain", "pool_address", "block_number", "completed_at")}
                self.row["audit_payload"] = json.loads(params["payload"])
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))
    async def scenario():
        session = Session()
        identity = dict(chain=original.chain, pool_address=original.pool_address, block_number=original.block_number)
        assert await audit.load_provider_attestation_audit(session, **identity) is None
        await audit.append_provider_attestation_audit(session, original)
        assert await audit.load_provider_attestation_audit(session, **identity) == original
        session.row["audit_payload"]["block_number"] += 1
        with pytest.raises(ValueError, match="identity mismatch"):
            await audit.load_provider_attestation_audit(session, **identity)
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["success", "disabled", "not_due", "observation_failure", "replay", "audit_failure", "commit_failure"])
def test_cli_audit_transaction_outcomes(monkeypatch, mode):
    events, durable, pending = [], [], []
    observers = tuple(SimpleNamespace(
        rpc_url=f"https://rpc-{name}.example/private/SECRET?key=SECRET",
        chain=SimpleNamespace(key="base", chain_id=8453), attest_chain=lambda: 8453,
    ) for name in ("a", "b"))
    monkeypatch.setattr(cli, "build_cli_observers", lambda *args: observers)
    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def execute(self, statement, params):
            events.append("audit")
            if mode == "audit_failure":
                raise RuntimeError("audit failure")
            pending.append(json.loads(params["payload"]))
        async def commit(self):
            events.append("commit")
            if mode == "commit_failure":
                raise RuntimeError("commit failure")
            durable.extend(pending)
            pending.clear()
        async def rollback(self):
            events.append("rollback")
            pending.clear()
    monkeypatch.setattr(cli, "SessionLocal", Session)
    async def invoke(*args, **kwargs):
        events.append("invoke")
        if mode in ("observation_failure", "replay"):
            raise ValueError(mode)
        skipped = mode in ("disabled", "not_due")
        return SimpleNamespace(
            trigger=SimpleNamespace(triggered=not skipped, run=None if skipped else object(),
                                    observed_at=record().completed_at, reason=mode),
            state=None if skipped else SimpleNamespace(chain="base", pool_address=payload().pool_address,
                last_completed_block=payload().block_number, last_completed_at=record().completed_at),
        )
    monkeypatch.setattr(cli, "invoke_reference_dex_observation", invoke)
    async def scenario():
        return await cli.execute_operator_payload(payload(), rpc_env_vars=("RPC_A", "RPC_B"))
    if mode in ("success", "disabled", "not_due"):
        result = asyncio.run(scenario())
        assert result["read_only"] is True and result["execution_authorized"] is False
    else:
        with pytest.raises((ValueError, RuntimeError)):
            asyncio.run(scenario())
        assert events[-1] == "rollback"
    assert not pending
    assert len(durable) == (1 if mode == "success" else 0)
    if mode in ("disabled", "not_due", "observation_failure", "replay"):
        assert "audit" not in events
    if mode == "success":
        assert events == ["invoke", "audit", "commit"]
        assert audit.decode_provider_attestation_audit(durable[0]) == record()


@pytest.mark.parametrize("mode", ["partial", "substituted", "wrong_chain"])
def test_invalid_full_set_fails_before_database(monkeypatch, mode):
    observers = tuple(SimpleNamespace(rpc_url=f"https://rpc-{name}.example") for name in ("a", "b"))
    monkeypatch.setattr(cli, "build_cli_observers", lambda *args: observers)
    rows = tuple(audit.ProviderAttestationReceipt(provider_fingerprint(o.rpc_url), "base", 8453) for o in observers)
    if mode == "partial":
        rows = rows[:1]
    elif mode == "wrong_chain":
        rows = (replace(rows[0], chain_id=1), rows[1])
    else:
        rows = (rows[0], replace(rows[1], provider="rpc-z.example:123456789abc"))
    monkeypatch.setattr(cli, "attest_cli_observers", lambda observers: rows)
    def forbidden():
        pytest.fail("invalid receipt reached database")
    monkeypatch.setattr(cli, "SessionLocal", forbidden)
    with pytest.raises((ValueError, cli.EvmRpcError)):
        asyncio.run(cli.execute_operator_payload(payload(), rpc_env_vars=("RPC_A", "RPC_B")))
