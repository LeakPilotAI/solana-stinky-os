from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence, FactoryRelationshipSource
from stinky_core.evm_implementation_registry import ImplementationFingerprintEntry
from stinky_core.evm_reference_dex_envelope import compose_reference_dex_evidence_envelope
from stinky_core.evm_reference_dex_record import compose_reference_dex_evidence_record
from stinky_core.evm_reference_materialization import ReferenceFingerprintBundle

FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
ROUTER = "0x" + "33" * 20
TOKEN0 = "0x" + "44" * 20
TOKEN1 = "0x" + "55" * 20
BLOCK = 123


def code(address, digest, block=BLOCK):
    return ContractCodeEvidence(
        chain="base", chain_id=8453, address=address,
        contract_key=f"base:{address}", block_number=block,
        byte_length=2, fingerprint_sha256=digest,
        runtime_bytecode="0x6001", status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("a", digest, 2), ContractCodeSource("b", digest, 2)),
    )


def relationship(factory_code, verdict="FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"):
    return FactoryRelationshipEvidence(
        "base", FACTORY, POOL, TOKEN0, TOKEN1, "V2_STYLE_PAIR_CREATED", None,
        BLOCK, factory_code, POOL,
        (FactoryRelationshipSource("provider-a", POOL), FactoryRelationshipSource("provider-b", POOL)),
        verdict, "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE",
        ("FACTORY_LOOKUP_DOES_NOT_PROVE_POOL_IMPLEMENTATION_AUTHENTICITY",),
    )


def entry(digest, role, ref):
    return ImplementationFingerprintEntry(
        digest, 2, role, "DEX_A", "v1", "TEST_REFERENCE", ref, ("base",),
    )


def bundle():
    rows = (
        entry("a" * 64, "FACTORY", "factory-ref"),
        entry("b" * 64, "POOL", "pool-ref"),
        entry("c" * 64, "ROUTER", "router-ref"),
    )
    return ReferenceFingerprintBundle(
        rows, tuple(row.source_reference for row in rows), (("base", BLOCK),),
        "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE", (),
    )


def components(router_block=BLOCK):
    return (
        code(FACTORY, "a" * 64),
        code(POOL, "b" * 64),
        code(ROUTER, "c" * 64, router_block),
    )


def test_record_retains_exact_relationship_and_envelope():
    factory_code, pool_code, router_code = components()
    relation = relationship(factory_code)
    source_bundle = bundle()
    result = compose_reference_dex_evidence_record(
        relation, factory_code, pool_code, router_code, source_bundle
    )
    assert result.relationship is relation
    assert result.relationship.sources[0].provider == "provider-a"
    assert result.relationship.returned_address == POOL
    assert result.envelope.source_references == source_bundle.source_references
    assert result.envelope.dex_family.verdict == "DEX_IMPLEMENTATION_FAMILY_CONSISTENT"
    assert result.status == "UNVERIFIED_REFERENCE_DEX_EVIDENCE_RECORD"


def test_record_preserves_envelope_verdict_parity():
    factory_code, pool_code, router_code = components()
    relation = relationship(factory_code)
    source_bundle = bundle()
    record = compose_reference_dex_evidence_record(
        relation, factory_code, pool_code, router_code, source_bundle
    )
    envelope = compose_reference_dex_evidence_envelope(
        relation, factory_code, pool_code, router_code, source_bundle
    )
    assert record.envelope == envelope


def test_record_preserves_unknown_relationship_evidence():
    factory_code, pool_code, router_code = components()
    relation = relationship(factory_code, "UNKNOWN_FACTORY_RELATIONSHIP")
    result = compose_reference_dex_evidence_record(
        relation, factory_code, pool_code, router_code, bundle()
    )
    assert result.relationship.relationship == "UNKNOWN_FACTORY_RELATIONSHIP"
    assert result.envelope.dex_family.verdict == "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"


def test_record_fails_closed_on_snapshot_mismatch():
    factory_code, pool_code, router_code = components(router_block=BLOCK + 1)
    with pytest.raises(ValueError, match="historical block"):
        compose_reference_dex_evidence_record(
            relationship(factory_code), factory_code, pool_code, router_code, bundle()
        )


def test_record_carries_non_authenticity_limitations():
    factory_code, pool_code, router_code = components()
    result = compose_reference_dex_evidence_record(
        relationship(factory_code), factory_code, pool_code, router_code, bundle()
    )
    assert "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE" in result.limitations
    assert "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY" in result.limitations
    assert "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_LIQUIDITY_QUALITY" in result.limitations
    assert "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations
    assert "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS" in result.limitations
