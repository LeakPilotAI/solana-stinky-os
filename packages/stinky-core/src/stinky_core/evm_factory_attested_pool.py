"""Conservative factory-attested pool deployment evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_factory_evidence import FactoryRelationshipEvidence

_MATCH = "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"
_NO_POOL = "FACTORY_LOOKUP_REPORTS_NO_POOL"
_CONFLICT = "FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL"
_UNKNOWN = "UNKNOWN_FACTORY_RELATIONSHIP"


@dataclass(frozen=True, slots=True)
class FactoryAttestedPoolDeploymentEvidence:
    relationship: FactoryRelationshipEvidence
    chain: str
    factory_address: str
    pool_address: str
    block_number: int
    verdict: str
    status: str
    limitations: tuple[str, ...]


def assess_factory_attested_pool_deployment(
    relationship: FactoryRelationshipEvidence,
) -> FactoryAttestedPoolDeploymentEvidence:
    """Classify only what the historical factory lookup actually attests.

    This is deliberately distinct from externally pinned deployment provenance.
    """
    if relationship.relationship == _MATCH:
        providers = tuple(source.provider for source in relationship.sources)
        if any(not isinstance(provider, str) or not provider.strip() for provider in providers) or len(set(providers)) < 2:
            raise ValueError("matching factory relationship requires distinct provider evidence")
        if relationship.returned_address != relationship.pool_address:
            raise ValueError("matching factory relationship must return the discovered pool")
        if any(source.returned_address != relationship.pool_address for source in relationship.sources):
            raise ValueError("matching factory relationship sources must return the discovered pool")
        verdict = "FACTORY_HISTORICALLY_ATTESTS_POOL"
    elif relationship.relationship in {_NO_POOL, _CONFLICT}:
        verdict = "FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT"
    elif relationship.relationship == _UNKNOWN:
        verdict = "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT"
    else:
        raise ValueError("unsupported factory relationship verdict")

    return FactoryAttestedPoolDeploymentEvidence(
        relationship=relationship,
        chain=relationship.chain,
        factory_address=relationship.factory_address,
        pool_address=relationship.pool_address,
        block_number=relationship.block_number,
        verdict=verdict,
        status="UNVERIFIED_FACTORY_ATTESTED_POOL_DEPLOYMENT_EVIDENCE",
        limitations=(
            "FACTORY_ATTESTATION_IS_NOT_EXTERNALLY_PINNED_DEPLOYMENT_PROVENANCE",
            "FACTORY_ATTESTATION_DOES_NOT_PROVE_FACTORY_IMPLEMENTATION_AUTHENTICITY",
            "FACTORY_ATTESTATION_DOES_NOT_PROVE_POOL_IMPLEMENTATION_AUTHENTICITY",
            "FACTORY_ATTESTATION_DOES_NOT_PROVE_DEPLOYMENT_ORIGIN",
            "FACTORY_ATTESTATION_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "FACTORY_ATTESTATION_DOES_NOT_PROVE_LIQUIDITY_QUALITY_OR_SAFETY",
            "FACTORY_ATTESTATION_IS_HISTORICAL_BLOCK_SCOPED",
        ),
    )
