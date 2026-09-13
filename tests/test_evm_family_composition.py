from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence
from stinky_core.evm_family_composition import compose_factory_pool_family_consistency
from stinky_core.evm_implementation_registry import (
    ImplementationFingerprintEvidence,
    ImplementationFingerprintMatch,
)

FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
TOKEN0 = "0x" + "33" * 20
TOKEN1 = "0x" + "44" * 20


def code(address=FACTORY, *, chain="base", block=100):
    return ContractCodeEvidence(
        chain=chain,
        chain_id=8453,
        address=address,
        contract_key=f"{chain}:{address}",
        block_number=block,
        byte_length=5,
        fingerprint_sha256="a" * 64,
        runtime_bytecode="0x6001600055",
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(),
    )


def relationship(*, value="FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", chain="base", block=100):
    return FactoryRelationshipEvidence(
        chain=chain,
        factory_address=FACTORY,
        pool_address=POOL,
        token0_address=TOKEN0,
        token1_address=TOKEN1,
        event_family="V2_STYLE_PAIR_CREATED",
        fee_tier=None,
        block_number=block,
        factory_code=code(FACTORY, chain=chain, block=block),
        returned_address=POOL if value == "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL" else None,
        sources=(),
        relationship=value,
        status="UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE",
        limitations=(),
    )


def fingerprint(address, role, family, *, chain="base", block=100, verdict="EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"):
    matches = () if family is None else (
        ImplementationFingerprintMatch(
            implementation_family=family,
            implementation_version="1",
            contract_role=role,
            source_kind="TEST_PROVENANCE",
            source_reference=f"fixture-{role.lower()}",
            chains=(chain,),
        ),
    )
    return ImplementationFingerprintEvidence(
        chain=chain,
        contract_key=f"{chain}:{address}",
        address=address,
        block_number=block,
        observed_fingerprint_sha256="b" * 64,
        observed_byte_length=5,
        expected_role=role,
        matches=matches,
        verdict=verdict,
        status="UNVERIFIED_IMPLEMENTATION_FINGERPRINT_EVIDENCE",
        limitations=(),
    )


def test_same_exact_family_is_consistent_at_same_historical_block():
    result = compose_factory_pool_family_consistency(
        relationship(),
        fingerprint(FACTORY, "FACTORY", "REFERENCE_V2"),
        fingerprint(POOL, "POOL", "REFERENCE_V2"),
    )
    assert result.verdict == "FACTORY_POOL_IMPLEMENTATION_FAMILY_CONSISTENT"
    assert result.factory_family == "REFERENCE_V2"
    assert result.pool_family == "REFERENCE_V2"
    assert result.block_number == 100
    assert result.status == "UNVERIFIED_FACTORY_POOL_FAMILY_CONSISTENCY_EVIDENCE"


def test_known_different_families_are_explicit_conflict():
    result = compose_factory_pool_family_consistency(
        relationship(),
        fingerprint(FACTORY, "FACTORY", "REFERENCE_V2"),
        fingerprint(POOL, "POOL", "OTHER_FAMILY"),
    )
    assert result.verdict == "FACTORY_POOL_IMPLEMENTATION_FAMILY_CONFLICT"


def test_missing_or_ambiguous_fingerprint_evidence_stays_unknown():
    unknown_pool = fingerprint(
        POOL,
        "POOL",
        None,
        verdict="UNKNOWN_IMPLEMENTATION_FINGERPRINT",
    )
    result = compose_factory_pool_family_consistency(
        relationship(),
        fingerprint(FACTORY, "FACTORY", "REFERENCE_V2"),
        unknown_pool,
    )
    assert result.verdict == "UNKNOWN_FACTORY_POOL_FAMILY_CONSISTENCY"
    assert "IMPLEMENTATION_FAMILY_EVIDENCE_INCOMPLETE_OR_AMBIGUOUS" in result.issues


def test_unconfirmed_factory_pool_relationship_stays_unknown():
    result = compose_factory_pool_family_consistency(
        relationship(value="FACTORY_LOOKUP_REPORTS_NO_POOL"),
        fingerprint(FACTORY, "FACTORY", "REFERENCE_V2"),
        fingerprint(POOL, "POOL", "REFERENCE_V2"),
    )
    assert result.verdict == "UNKNOWN_FACTORY_POOL_FAMILY_CONSISTENCY"
    assert result.issues == ("FACTORY_POOL_RELATIONSHIP_NOT_CONFIRMED",)


def test_chain_block_address_and_role_mismatches_fail_closed():
    with pytest.raises(ValueError, match="chain"):
        compose_factory_pool_family_consistency(
            relationship(),
            fingerprint(FACTORY, "FACTORY", "REFERENCE_V2", chain="robinhood"),
            fingerprint(POOL, "POOL", "REFERENCE_V2"),
        )
    with pytest.raises(ValueError, match="historical block"):
        compose_factory_pool_family_consistency(
            relationship(),
            fingerprint(FACTORY, "FACTORY", "REFERENCE_V2", block=99),
            fingerprint(POOL, "POOL", "REFERENCE_V2"),
        )
    with pytest.raises(ValueError, match="factory fingerprint address"):
        compose_factory_pool_family_consistency(
            relationship(),
            fingerprint(POOL, "FACTORY", "REFERENCE_V2"),
            fingerprint(POOL, "POOL", "REFERENCE_V2"),
        )
    with pytest.raises(ValueError, match="FACTORY role"):
        compose_factory_pool_family_consistency(
            relationship(),
            fingerprint(FACTORY, "POOL", "REFERENCE_V2"),
            fingerprint(POOL, "POOL", "REFERENCE_V2"),
        )


def test_consistency_result_keeps_non_authenticity_limitations():
    result = compose_factory_pool_family_consistency(
        relationship(),
        fingerprint(FACTORY, "FACTORY", "REFERENCE_V2"),
        fingerprint(POOL, "POOL", "REFERENCE_V2"),
    )
    assert "FAMILY_CONSISTENCY_DOES_NOT_PROVE_FACTORY_OR_POOL_AUTHENTICITY" in result.limitations
    assert "FAMILY_CONSISTENCY_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations
