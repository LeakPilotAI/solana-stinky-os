from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence
from stinky_core.evm_implementation_registry import ImplementationFingerprintEntry
from stinky_core.evm_reference_dex_composition import compose_reference_bundle_dex_family
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


def relationship(factory_code, relationship="FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"):
    return FactoryRelationshipEvidence(
        "base", FACTORY, POOL, TOKEN0, TOKEN1, "V2_STYLE_PAIR_CREATED", None,
        BLOCK, factory_code, POOL, (), relationship,
        "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE", (),
    )


def entry(digest, role, family, ref):
    return ImplementationFingerprintEntry(
        digest, 2, role, family, "v1", "TEST_REFERENCE", ref, ("base",),
    )


def bundle(factory_family="DEX_A", pool_family="DEX_A", router_family="DEX_A"):
    rows = (
        entry("a" * 64, "FACTORY", factory_family, "factory-ref"),
        entry("b" * 64, "POOL", pool_family, "pool-ref"),
        entry("c" * 64, "ROUTER", router_family, "router-ref"),
    )
    return ReferenceFingerprintBundle(
        rows, tuple(row.source_reference for row in rows), (("base", BLOCK),),
        "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE", (),
    )


def components(block=BLOCK):
    return (
        code(FACTORY, "a" * 64, block),
        code(POOL, "b" * 64, block),
        code(ROUTER, "c" * 64, block),
    )


def test_bundle_composes_consistent_dex_family():
    factory_code, pool_code, router_code = components()
    result = compose_reference_bundle_dex_family(
        relationship(factory_code), factory_code, pool_code, router_code, bundle()
    )
    assert result.verdict == "DEX_IMPLEMENTATION_FAMILY_CONSISTENT"
    assert result.factory_family == result.pool_family == result.router_family == "DEX_A"
    assert result.block_number == BLOCK


def test_bundle_composes_known_router_conflict():
    factory_code, pool_code, router_code = components()
    result = compose_reference_bundle_dex_family(
        relationship(factory_code), factory_code, pool_code, router_code,
        bundle(router_family="DEX_B"),
    )
    assert result.verdict == "DEX_IMPLEMENTATION_FAMILY_CONFLICT"


def test_bundle_preserves_unknown_component_behavior():
    factory_code, pool_code, router_code = components()
    pool_code = code(POOL, "d" * 64)
    result = compose_reference_bundle_dex_family(
        relationship(factory_code), factory_code, pool_code, router_code, bundle()
    )
    assert result.verdict == "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"


def test_bundle_requires_relationship_identity_and_snapshot():
    factory_code, pool_code, router_code = components()
    with pytest.raises(ValueError, match="factory code address"):
        compose_reference_bundle_dex_family(
            relationship(factory_code), code("0x" + "66" * 20, "a" * 64),
            pool_code, router_code, bundle(),
        )
    with pytest.raises(ValueError, match="historical block"):
        compose_reference_bundle_dex_family(
            relationship(factory_code), factory_code, pool_code,
            code(ROUTER, "c" * 64, BLOCK + 1), bundle(),
        )


def test_bundle_provenance_and_relationship_fail_closed():
    factory_code, pool_code, router_code = components()
    bad_bundle = ReferenceFingerprintBundle(
        bundle().entries, ("wrong-ref",), (("base", BLOCK),),
        "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE", (),
    )
    with pytest.raises(ValueError, match="provenance"):
        compose_reference_bundle_dex_family(
            relationship(factory_code), factory_code, pool_code, router_code, bad_bundle,
        )
    result = compose_reference_bundle_dex_family(
        relationship(factory_code, "UNKNOWN_FACTORY_RELATIONSHIP"),
        factory_code, pool_code, router_code, bundle(),
    )
    assert result.verdict == "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"
