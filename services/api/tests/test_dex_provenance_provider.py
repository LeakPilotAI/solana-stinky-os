from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import stinky_api.dex_provenance_provider as provider_module
from stinky_api.dex_provenance_provider import PostgresDexProvenanceEvidenceProvider
from stinky_api.dex_provenance_store import PersistedDexProvenanceEvidence
from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_dex_family_composition import DexFamilyConsistencyEvidence
from stinky_core.evm_dex_provenance_codec import (
    decode_reference_dex_evidence_record,
    encode_reference_dex_evidence_record,
    encode_reference_sources,
)
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence, FactoryRelationshipSource
from stinky_core.evm_implementation_registry import ImplementationFingerprintEvidence, ImplementationFingerprintMatch
from stinky_core.evm_reference_dex_envelope import ReferenceDexEvidenceEnvelope
from stinky_core.evm_reference_dex_record import ReferenceDexEvidenceRecord
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource

CHAIN = "base"
POOL = "0x1111111111111111111111111111111111111111"
FACTORY = "0x2222222222222222222222222222222222222222"
ROUTER = "0x3333333333333333333333333333333333333333"
TOKEN0 = "0x4444444444444444444444444444444444444444"
TOKEN1 = "0x5555555555555555555555555555555555555555"
BLOCK = 123
DIGEST = "a" * 64


def code(address):
    return ContractCodeEvidence(
        chain=CHAIN,
        chain_id=8453,
        address=address,
        contract_key=f"{CHAIN}:{address}",
        block_number=BLOCK,
        byte_length=1,
        fingerprint_sha256=DIGEST,
        runtime_bytecode="0x00",
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("provider-a", DIGEST, 1),),
    )


def fingerprint(address, role):
    match = ImplementationFingerprintMatch("UNISWAP_V2", "V2", role, "PINNED", "ref", (CHAIN,))
    return ImplementationFingerprintEvidence(
        CHAIN, f"{CHAIN}:{address}", address, BLOCK, DIGEST, 1, role,
        (match,), "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH",
        "UNVERIFIED_IMPLEMENTATION_FINGERPRINT_EVIDENCE", ("limited",),
    )


def record():
    factory_code = code(FACTORY)
    relationship = FactoryRelationshipEvidence(
        CHAIN, FACTORY, POOL, TOKEN0, TOKEN1, "V2_STYLE_PAIR_CREATED", None, BLOCK,
        factory_code, POOL, (FactoryRelationshipSource("provider-a", POOL),),
        "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE",
        ("relationship-limit",),
    )
    dex_family = DexFamilyConsistencyEvidence(
        CHAIN, BLOCK, "UNISWAP_V2", "UNISWAP_V2", "UNISWAP_V2",
        "DEX_IMPLEMENTATION_FAMILY_CONSISTENT", "UNVERIFIED_DEX_FAMILY_CONSISTENCY_EVIDENCE",
        (), ("family-limit",),
    )
    envelope = ReferenceDexEvidenceEnvelope(
        ("github:source",), ((CHAIN, BLOCK),),
        fingerprint(FACTORY, "FACTORY"), fingerprint(POOL, "POOL"), fingerprint(ROUTER, "ROUTER"),
        dex_family, "UNVERIFIED_REFERENCE_DEX_EVIDENCE_ENVELOPE", ("envelope-limit",),
    )
    return ReferenceDexEvidenceRecord(
        relationship, envelope, "UNVERIFIED_REFERENCE_DEX_EVIDENCE_RECORD", ("record-limit",),
    )


def source():
    return DexReferenceContractSource(
        chain=CHAIN,
        address=FACTORY,
        contract_role="FACTORY",
        implementation_family="UNISWAP_V2",
        implementation_version="V2",
        source_repository="Uniswap/sdk-core",
        source_commit="baff6d3c78b09aa0b2f96148bc223b42a57fd28a",
        source_path="src/addresses.ts",
        source_locator="V2_FACTORY_ADDRESSES.base",
    )


def persisted(rec=None, sources=None):
    rec = rec or record()
    sources = sources or (source(),)
    return PersistedDexProvenanceEvidence(
        id=1,
        chain=CHAIN,
        pool_address=POOL,
        evidence_block=BLOCK,
        evidence_key="key",
        record_payload=encode_reference_dex_evidence_record(rec),
        sources_payload=encode_reference_sources(sources),
        observed_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )


def test_codec_round_trips_exact_record_and_source_tuple():
    original = record()
    payload = encode_reference_dex_evidence_record(original)
    restored = decode_reference_dex_evidence_record(payload)
    assert restored == original
    assert restored.relationship.factory_code == original.relationship.factory_code
    assert restored.envelope.chain_blocks == ((CHAIN, BLOCK),)


def test_codec_rejects_unknown_version_and_unknown_type():
    payload = encode_reference_dex_evidence_record(record())
    payload["version"] = 999
    with pytest.raises(ValueError):
        decode_reference_dex_evidence_record(payload)

    payload = encode_reference_dex_evidence_record(record())
    payload["value"]["__type__"] = "UnknownEvidence"
    with pytest.raises(ValueError):
        decode_reference_dex_evidence_record(payload)


@pytest.mark.asyncio
async def test_postgres_provider_returns_typed_bundle_without_synthesis(monkeypatch):
    row = persisted()

    async def fake_load(session, *, chain, pool_address):
        assert chain == CHAIN
        assert pool_address == POOL
        return row

    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    provider = PostgresDexProvenanceEvidenceProvider(SimpleNamespace())
    bundle = await provider.load(chain=CHAIN, pool_address=POOL)

    assert bundle is not None
    assert bundle.record == record()
    assert bundle.sources == (source(),)


@pytest.mark.asyncio
async def test_postgres_provider_preserves_missing_evidence(monkeypatch):
    async def fake_load(session, *, chain, pool_address):
        return None

    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    provider = PostgresDexProvenanceEvidenceProvider(SimpleNamespace())
    assert await provider.load(chain=CHAIN, pool_address=POOL) is None


@pytest.mark.asyncio
async def test_postgres_provider_fails_closed_on_identity_mismatch(monkeypatch):
    row = persisted()
    row = PersistedDexProvenanceEvidence(
        row.id, row.chain, "0x9999999999999999999999999999999999999999", row.evidence_block,
        row.evidence_key, row.record_payload, row.sources_payload, row.observed_at,
    )

    async def fake_load(session, *, chain, pool_address):
        return row

    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    provider = PostgresDexProvenanceEvidenceProvider(SimpleNamespace())
    with pytest.raises(ValueError):
        await provider.load(chain=CHAIN, pool_address=POOL)
