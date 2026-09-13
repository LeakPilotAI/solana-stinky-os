from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence
from stinky_core.evm_implementation_registry import ImplementationFingerprintEntry
from stinky_core.evm_reference_dex_authenticity import assess_reference_dex_authenticity
from stinky_core.evm_reference_dex_record import compose_reference_dex_evidence_record
from stinky_core.evm_reference_materialization import ReferenceFingerprintBundle

FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
ROUTER = "0x" + "33" * 20
TOKEN0 = "0x" + "44" * 20
TOKEN1 = "0x" + "55" * 20
BLOCK = 123


def code(address, digest):
    return ContractCodeEvidence(
        chain="base", chain_id=8453, address=address,
        contract_key=f"base:{address}", block_number=BLOCK,
        byte_length=2, fingerprint_sha256=digest,
        runtime_bytecode="0x6001", status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("a", digest, 2), ContractCodeSource("b", digest, 2)),
    )


def relationship(factory_code, verdict="FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"):
    returned = POOL if verdict == "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL" else None
    return FactoryRelationshipEvidence(
        "base", FACTORY, POOL, TOKEN0, TOKEN1, "V2_STYLE_PAIR_CREATED", None,
        BLOCK, factory_code, returned, (), verdict,
        "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE", (),
    )


def entry(digest, role, family, ref):
    return ImplementationFingerprintEntry(
        digest, 2, role, family, "v1", "TEST_REFERENCE", ref, ("base",),
    )


def bundle(router_family="DEX_A", include_pool=True):
    rows = [
        entry("a" * 64, "FACTORY", "DEX_A", "factory-ref"),
        entry("c" * 64, "ROUTER", router_family, "router-ref"),
    ]
    if include_pool:
        rows.append(entry("b" * 64, "POOL", "DEX_A", "pool-ref"))
    rows = tuple(rows)
    return ReferenceFingerprintBundle(
        rows, tuple(row.source_reference for row in rows), (("base", BLOCK),),
        "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE", (),
    )


def record(*, relation="FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", router_family="DEX_A", include_pool=True):
    factory_code = code(FACTORY, "a" * 64)
    pool_code = code(POOL, "b" * 64)
    router_code = code(ROUTER, "c" * 64)
    return compose_reference_dex_evidence_record(
        relationship(factory_code, relation), factory_code, pool_code, router_code,
        bundle(router_family=router_family, include_pool=include_pool),
    )


def test_exact_reference_components_match_without_claiming_safety():
    result = assess_reference_dex_authenticity(record())
    assert result.factory == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.pool == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.router == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.relationship == "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"
    assert result.dex_family == "DEX_IMPLEMENTATION_FAMILY_CONSISTENT"
    assert result.verdict == "REFERENCE_DEX_COMPONENTS_MATCH"
    assert result.status == "UNVERIFIED_REFERENCE_DEX_AUTHENTICITY_ASSESSMENT"
    assert "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations
    assert "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_DEPLOYMENT_ORIGIN" in result.limitations


def test_unknown_component_remains_unknown_authenticity():
    result = assess_reference_dex_authenticity(record(include_pool=False))
    assert result.pool == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_AUTHENTICITY"


def test_unknown_relationship_remains_unknown_authenticity():
    result = assess_reference_dex_authenticity(record(relation="UNKNOWN_FACTORY_RELATIONSHIP"))
    assert result.relationship == "UNKNOWN_FACTORY_RELATIONSHIP"
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_AUTHENTICITY"


def test_known_family_conflict_is_explicit_conflict():
    result = assess_reference_dex_authenticity(record(router_family="DEX_B"))
    assert result.dex_family == "DEX_IMPLEMENTATION_FAMILY_CONFLICT"
    assert result.verdict == "REFERENCE_DEX_COMPONENT_EVIDENCE_CONFLICT"


def test_known_factory_relationship_conflict_is_explicit_conflict():
    result = assess_reference_dex_authenticity(
        record(relation="FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL")
    )
    assert result.relationship == "FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL"
    assert result.verdict == "REFERENCE_DEX_COMPONENT_EVIDENCE_CONFLICT"


def test_positive_assessment_is_historical_and_non_execution_evidence():
    result = assess_reference_dex_authenticity(record())
    assert "REFERENCE_COMPONENT_MATCH_IS_HISTORICAL_BLOCK_SCOPED" in result.limitations
    assert "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED" in result.limitations
    assert "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_LIQUIDITY_QUALITY" in result.limitations
    assert "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS" in result.limitations
