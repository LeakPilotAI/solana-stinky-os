"""Conservative evidence-tier assessment for pool deployment identity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_factory_attested_pool import (
    FactoryAttestedPoolDeploymentEvidence,
    assess_factory_attested_pool_deployment,
)
from .evm_reference_deployment_identity import (
    ReferenceDeploymentIdentityAssessment,
    assess_reference_deployment_address,
)
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource

_PINNED_MATCH = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"
_PINNED_CONFLICT = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"
_PINNED_UNKNOWN = "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"
_ATTESTED = "FACTORY_HISTORICALLY_ATTESTS_POOL"
_ATTESTED_CONFLICT = "FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT"
_ATTESTED_UNKNOWN = "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT"


@dataclass(frozen=True, slots=True)
class PoolDeploymentEvidenceTierAssessment:
    pinned_deployment: ReferenceDeploymentIdentityAssessment
    factory_attestation: FactoryAttestedPoolDeploymentEvidence
    chain: str
    pool_address: str
    tier: str
    verdict: str
    status: str
    limitations: tuple[str, ...]


def assess_pool_deployment_evidence_tier(
    pinned_deployment: ReferenceDeploymentIdentityAssessment,
    factory_attestation: FactoryAttestedPoolDeploymentEvidence,
) -> PoolDeploymentEvidenceTierAssessment:
    """Classify pool deployment evidence without conflating provenance sources."""
    if pinned_deployment.contract_role != "POOL":
        raise ValueError("pinned deployment evidence must use POOL role")
    if pinned_deployment.chain != factory_attestation.chain:
        raise ValueError("pool deployment evidence must share a chain")
    if pinned_deployment.address != factory_attestation.pool_address:
        raise ValueError("pool deployment evidence must share a pool address")

    pinned_verdict = pinned_deployment.verdict
    attested_verdict = factory_attestation.verdict

    if pinned_verdict == _PINNED_CONFLICT or attested_verdict == _ATTESTED_CONFLICT:
        tier = "POOL_DEPLOYMENT_EVIDENCE_CONFLICT"
        verdict = "POOL_DEPLOYMENT_EVIDENCE_CONFLICT"
    elif pinned_verdict == _PINNED_MATCH:
        tier = "EXTERNALLY_PINNED_POOL_DEPLOYMENT"
        verdict = "EXTERNALLY_PINNED_POOL_DEPLOYMENT_MATCH"
    elif pinned_verdict == _PINNED_UNKNOWN and attested_verdict == _ATTESTED:
        tier = "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"
        verdict = "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"
    elif pinned_verdict == _PINNED_UNKNOWN and attested_verdict == _ATTESTED_UNKNOWN:
        tier = "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE"
        verdict = "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE"
    else:
        raise ValueError("unsupported pool deployment evidence verdict combination")

    return PoolDeploymentEvidenceTierAssessment(
        pinned_deployment=pinned_deployment,
        factory_attestation=factory_attestation,
        chain=pinned_deployment.chain,
        pool_address=pinned_deployment.address,
        tier=tier,
        verdict=verdict,
        status="UNVERIFIED_POOL_DEPLOYMENT_EVIDENCE_TIER_ASSESSMENT",
        limitations=(
            "FACTORY_ATTESTATION_IS_NOT_EXTERNALLY_PINNED_DEPLOYMENT_PROVENANCE",
            "POOL_DEPLOYMENT_EVIDENCE_TIER_DOES_NOT_PROVE_DEPLOYMENT_ORIGIN",
            "POOL_DEPLOYMENT_EVIDENCE_TIER_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "POOL_DEPLOYMENT_EVIDENCE_TIER_DOES_NOT_PROVE_POOL_IMPLEMENTATION_AUTHENTICITY",
            "POOL_DEPLOYMENT_EVIDENCE_TIER_DOES_NOT_PROVE_LIQUIDITY_QUALITY_OR_SAFETY",
            "POOL_DEPLOYMENT_EVIDENCE_TIER_DOES_NOT_CHANGE_REFERENCE_DEX_IDENTITY_CONFIRMATION_RULES",
        ),
    )


def assess_pool_deployment_evidence_tier_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> PoolDeploymentEvidenceTierAssessment:
    """Build a pool evidence tier directly from preserved record evidence."""
    pool = record.envelope.pool_fingerprint
    pinned = assess_reference_deployment_address(
        pool.chain,
        pool.address,
        tuple(sources),
        expected_role="POOL",
    )
    attested = assess_factory_attested_pool_deployment(record.relationship)
    return assess_pool_deployment_evidence_tier(pinned, attested)
