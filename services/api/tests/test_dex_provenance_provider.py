from datetime import datetime, timezone
from dataclasses import replace
from copy import deepcopy
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
    decode_reference_sources,
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


def mismatched_records():
    original = record()
    for component in ("factory_fingerprint", "pool_fingerprint", "router_fingerprint"):
        for field, value in (("chain", "robinhood"), ("block_number", BLOCK + 1), ("expected_role", "UNKNOWN")):
            changed = replace(getattr(original.envelope, component), **{field: value})
            yield replace(original, envelope=replace(original.envelope, **{component: changed}))
    for component in ("factory_fingerprint", "pool_fingerprint"):
        changed = replace(getattr(original.envelope, component), address=ROUTER)
        yield replace(original, envelope=replace(original.envelope, **{component: changed}))
    for field, value in (("chain", "robinhood"), ("block_number", BLOCK + 1), ("address", ROUTER)):
        changed = replace(original.relationship.factory_code, **{field: value})
        yield replace(original, relationship=replace(original.relationship, factory_code=changed))
    for blocks in ((), ((CHAIN, BLOCK + 1),), ((CHAIN, BLOCK), (CHAIN, BLOCK + 1))):
        yield replace(original, envelope=replace(original.envelope, chain_blocks=blocks))


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", list(mismatched_records()))
async def test_provider_and_writer_reject_nested_identity_mismatch(monkeypatch, invalid):
    import stinky_api.dex_provenance_writer as writer
    row = persisted(invalid)
    async def fake_load(*args, **kwargs):
        return row
    async def forbidden_append(*args, **kwargs):
        pytest.fail("inconsistent historical evidence reached append")
    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    monkeypatch.setattr(writer, "append_dex_provenance_evidence", forbidden_append)
    with pytest.raises(ValueError, match="identity mismatch"):
        await PostgresDexProvenanceEvidenceProvider(SimpleNamespace()).load(chain=CHAIN, pool_address=POOL)
    with pytest.raises(ValueError, match="identity mismatch"):
        await writer.persist_dex_provenance_evidence(object(), record=invalid, sources=(source(),))


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["UNKNOWN_IMPLEMENTATION_FINGERPRINT", "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT"])
async def test_valid_identity_preserves_unknown_and_conflicting_evidence(monkeypatch, verdict):
    import stinky_api.dex_provenance_writer as writer
    original = record()
    original = replace(original, envelope=replace(original.envelope,
        pool_fingerprint=replace(original.envelope.pool_fingerprint, verdict=verdict),
        chain_blocks=((CHAIN, BLOCK), ("robinhood", 456)),
    ))
    row = persisted(original)
    async def fake_load(*args, **kwargs):
        return row
    captured = []
    async def append(session, **kwargs):
        captured.append(kwargs["record_payload"])
        return 41
    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    monkeypatch.setattr(writer, "append_dex_provenance_evidence", append)
    bundle = await PostgresDexProvenanceEvidenceProvider(SimpleNamespace()).load(chain=CHAIN, pool_address=POOL)
    assert bundle.record == original
    assert await writer.persist_dex_provenance_evidence(object(), record=original, sources=(source(),)) == 41
    assert decode_reference_dex_evidence_record(captured[0]) == original


_BAD_FIELDS = [
    (("relationship", "factory_code", "byte_length"), True, True),
    (("relationship", "factory_code", "byte_length"), "1", "1"),
    (("relationship", "factory_code", "chain"), 8453, 8453),
    (("relationship", "fee_tier"), False, False),
    (("relationship", "returned_address"), 1, 1),
    (("limitations",), "not a tuple", "not a tuple"),
    (("limitations",), (1,), {"__tuple__": [1]}),
    (("envelope", "chain_blocks"), ((CHAIN,),), {"__tuple__": [{"__tuple__": [CHAIN]}]}),
    (("envelope", "chain_blocks"), ((CHAIN, True),), {"__tuple__": [{"__tuple__": [CHAIN, True]}]}),
    (("envelope", "pool_fingerprint"), code(POOL), encode_reference_dex_evidence_record(record())["value"]["fields"]["relationship"]["fields"]["factory_code"]),
]


def replace_nested(value, path, replacement):
    field, *rest = path
    return replace(value, **{field: replace_nested(getattr(value, field), rest, replacement) if rest else replacement})


@pytest.mark.asyncio
@pytest.mark.parametrize("path, invalid, encoded", _BAD_FIELDS)
async def test_codec_type_errors_reject_read_and_write(monkeypatch, path, invalid, encoded):
    import stinky_api.dex_provenance_writer as writer
    original_row = persisted()
    corrupted = deepcopy(original_row.record_payload)
    target = corrupted["value"]
    for field in path[:-1]:
        target = target["fields"][field]
    target["fields"][path[-1]] = encoded
    row = replace(original_row, record_payload=corrupted)
    async def fake_load(*args, **kwargs):
        return row
    async def forbidden_append(*args, **kwargs):
        pytest.fail("malformed typed evidence reached append")
    monkeypatch.setattr(provider_module, "load_latest_dex_provenance_evidence", fake_load)
    monkeypatch.setattr(writer, "append_dex_provenance_evidence", forbidden_append)
    with pytest.raises(ValueError, match="field type"):
        decode_reference_dex_evidence_record(corrupted)
    with pytest.raises(ValueError, match="field type"):
        await PostgresDexProvenanceEvidenceProvider(SimpleNamespace()).load(chain=CHAIN, pool_address=POOL)
    bad_record = replace_nested(record(), path, invalid)
    with pytest.raises(ValueError, match="field type"):
        encode_reference_dex_evidence_record(bad_record)
    with pytest.raises(ValueError):
        await writer.persist_dex_provenance_evidence(object(), record=bad_record, sources=(source(),))


@pytest.mark.parametrize("version", [True, 1.0, "1", None])
def test_codec_requires_exact_integer_version(version):
    encoded = encode_reference_dex_evidence_record(record())
    encoded["version"] = version
    with pytest.raises(ValueError, match="schema version"):
        decode_reference_dex_evidence_record(encoded)
    sources = list(encode_reference_sources((source(),)))
    sources[0]["version"] = version
    with pytest.raises(ValueError, match="schema version"):
        decode_reference_sources(sources)


def test_source_field_types_fail_before_constructor_attribute_errors():
    encoded = list(encode_reference_sources((source(),)))
    encoded[0]["value"]["fields"]["source_repository"] = 42
    with pytest.raises(ValueError, match="field type"):
        decode_reference_sources(encoded)
    with pytest.raises(ValueError, match="wrong type"):
        encode_reference_sources((code(POOL),))
    with pytest.raises(ValueError, match="ReferenceDexEvidenceRecord"):
        encode_reference_dex_evidence_record(code(POOL))


@pytest.mark.parametrize("fee", [None, 0, 3000])
def test_codec_preserves_nullable_fields_and_fixed_tuple_structure(fee):
    original = record()
    original = replace(original,
        relationship=replace(original.relationship, fee_tier=fee, returned_address=None),
        envelope=replace(original.envelope, dex_family=replace(original.envelope.dex_family, pool_family=None)),
    )
    assert decode_reference_dex_evidence_record(encode_reference_dex_evidence_record(original)) == original
    assert decode_reference_sources(encode_reference_sources((source(),))) == (source(),)
