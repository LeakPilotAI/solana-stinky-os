from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_reference_deployment_identity import (
    assess_reference_deployment_address,
    assess_reference_deployment_identity,
)
from stinky_core.evm_reference_fingerprints import BASE_UNISWAP_REFERENCE_SOURCES

BLOCK = 123


def code(address):
    digest = "a" * 64
    return ContractCodeEvidence(
        chain="base", chain_id=8453, address=address,
        contract_key=f"base:{address}", block_number=BLOCK,
        byte_length=2, fingerprint_sha256=digest,
        runtime_bytecode="0x6001", status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("a", digest, 2), ContractCodeSource("b", digest, 2)),
    )


def test_pinned_factory_address_is_explicit_identity_match():
    source = next(item for item in BASE_UNISWAP_REFERENCE_SOURCES if item.contract_role == "FACTORY")
    result = assess_reference_deployment_identity(
        code(source.address), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="FACTORY"
    )
    assert result.verdict == "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"
    assert result.matching_source_references == (source.source_reference,)
    assert result.status == "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT"


def test_address_native_primitive_matches_legacy_wrapper():
    source = next(item for item in BASE_UNISWAP_REFERENCE_SOURCES if item.contract_role == "ROUTER")
    legacy = assess_reference_deployment_identity(
        code(source.address), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="ROUTER"
    )
    native = assess_reference_deployment_address(
        "base", source.address, BASE_UNISWAP_REFERENCE_SOURCES, expected_role="ROUTER"
    )
    assert native == legacy


def test_different_factory_address_is_explicit_identity_conflict():
    result = assess_reference_deployment_identity(
        code("0x" + "11" * 20), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="FACTORY"
    )
    assert result.verdict == "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"
    assert result.matching_source_references == ()


def test_pool_identity_remains_unknown_when_catalog_has_no_pool_deployment():
    result = assess_reference_deployment_identity(
        code("0x" + "22" * 20), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="POOL"
    )
    assert result.verdict == "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"
    assert result.matching_source_references == ()


def test_router_address_is_role_scoped_not_factory_identity():
    router = next(item for item in BASE_UNISWAP_REFERENCE_SOURCES if item.contract_role == "ROUTER")
    result = assess_reference_deployment_identity(
        code(router.address), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="FACTORY"
    )
    assert result.verdict == "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"


def test_positive_identity_does_not_claim_implementation_or_safety():
    source = next(item for item in BASE_UNISWAP_REFERENCE_SOURCES if item.contract_role == "ROUTER")
    result = assess_reference_deployment_identity(
        code(source.address), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="ROUTER"
    )
    assert "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_RUNTIME_IMPLEMENTATION_IDENTITY" in result.limitations
    assert "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED" in result.limitations
    assert "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations
    assert "DEPLOYMENT_IDENTITY_DEPENDS_ON_PINNED_SOURCE_CATALOG_COVERAGE" in result.limitations


def test_role_validation_fails_closed():
    try:
        assess_reference_deployment_identity(
            code("0x" + "11" * 20), BASE_UNISWAP_REFERENCE_SOURCES, expected_role="TOKEN"
        )
    except ValueError as exc:
        assert "expected_role" in str(exc)
    else:
        raise AssertionError("unsupported deployment role must fail closed")
