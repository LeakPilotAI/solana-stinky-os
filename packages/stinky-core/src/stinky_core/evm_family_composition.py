"""Compose historical factory/pool evidence with implementation-family evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .evidence_pairing import compare_labels
from .evm_factory_evidence import FactoryRelationshipEvidence
from .evm_implementation_registry import ImplementationFingerprintEvidence


@dataclass(frozen=True, slots=True)
class FactoryPoolFamilyConsistencyEvidence:
    chain: str
    block_number: int
    factory_address: str
    pool_address: str
    factory_family: str | None
    pool_family: str | None
    verdict: str
    status: str
    issues: tuple[str, ...]
    limitations: tuple[str, ...]


def _resolved_family(evidence: ImplementationFingerprintEvidence, expected_role: str) -> str | None:
    if evidence.expected_role != expected_role:
        raise ValueError(f"fingerprint evidence must have {expected_role} role")
    if evidence.verdict != "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH":
        return None
    families = {match.implementation_family for match in evidence.matches}
    if len(families) != 1:
        return None
    return next(iter(families))


def compose_factory_pool_family_consistency(
    relationship: FactoryRelationshipEvidence,
    factory_fingerprint: ImplementationFingerprintEvidence,
    pool_fingerprint: ImplementationFingerprintEvidence,
) -> FactoryPoolFamilyConsistencyEvidence:
    """Combine already-observed evidence without adding new external observations."""
    if factory_fingerprint.chain != relationship.chain or pool_fingerprint.chain != relationship.chain:
        raise ValueError("family evidence must share the relationship chain")
    if factory_fingerprint.block_number != relationship.block_number or pool_fingerprint.block_number != relationship.block_number:
        raise ValueError("family evidence must share the relationship historical block")
    if factory_fingerprint.address != relationship.factory_address:
        raise ValueError("factory fingerprint address does not match relationship factory")
    if pool_fingerprint.address != relationship.pool_address:
        raise ValueError("pool fingerprint address does not match relationship pool")

    factory_family = _resolved_family(factory_fingerprint, "FACTORY")
    pool_family = _resolved_family(pool_fingerprint, "POOL")
    issues: list[str] = []

    if relationship.relationship != "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL":
        issues.append("FACTORY_POOL_RELATIONSHIP_NOT_CONFIRMED")
        verdict = "UNKNOWN_FACTORY_POOL_FAMILY_CONSISTENCY"
    else:
        paired = compare_labels(factory_family, pool_family)
        if paired.verdict == "CONSISTENT":
            verdict = "FACTORY_POOL_IMPLEMENTATION_FAMILY_CONSISTENT"
        elif paired.verdict == "CONFLICT":
            verdict = "FACTORY_POOL_IMPLEMENTATION_FAMILY_CONFLICT"
        else:
            verdict = "UNKNOWN_FACTORY_POOL_FAMILY_CONSISTENCY"
            issues.append("IMPLEMENTATION_FAMILY_EVIDENCE_INCOMPLETE_OR_AMBIGUOUS")

    return FactoryPoolFamilyConsistencyEvidence(
        chain=relationship.chain,
        block_number=relationship.block_number,
        factory_address=relationship.factory_address,
        pool_address=relationship.pool_address,
        factory_family=factory_family,
        pool_family=pool_family,
        verdict=verdict,
        status="UNVERIFIED_FACTORY_POOL_FAMILY_CONSISTENCY_EVIDENCE",
        issues=tuple(issues),
        limitations=(
            "FAMILY_CONSISTENCY_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "FAMILY_CONSISTENCY_DOES_NOT_PROVE_FACTORY_OR_POOL_AUTHENTICITY",
            "FAMILY_CONSISTENCY_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "FAMILY_CONSISTENCY_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "FAMILY_CONSISTENCY_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
        ),
    )
