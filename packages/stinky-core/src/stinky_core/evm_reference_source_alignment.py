"""Align implementation fingerprint lineage with pinned deployment-source lineage."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_implementation_registry import ImplementationFingerprintEvidence
from .evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from .evm_reference_fingerprints import DexReferenceContractSource


@dataclass(frozen=True, slots=True)
class ReferenceSourceAlignmentAssessment:
    contract_role: str
    implementation_lineages: tuple[tuple[str, str], ...]
    deployment_lineages: tuple[tuple[str, str], ...]
    verdict: str
    status: str
    limitations: tuple[str, ...]


def assess_reference_source_alignment(
    implementation: ImplementationFingerprintEvidence,
    deployment: ReferenceDeploymentIdentityAssessment,
    sources: Iterable[DexReferenceContractSource],
) -> ReferenceSourceAlignmentAssessment:
    """Check that implementation and deployment evidence point to the same lineage."""
    if implementation.chain != deployment.chain:
        raise ValueError("implementation and deployment evidence must share a chain")
    if implementation.address != deployment.address:
        raise ValueError("implementation and deployment evidence must share an address")
    if implementation.expected_role != deployment.contract_role:
        raise ValueError("implementation and deployment evidence must share a role")

    implementation_lineages = tuple(sorted({
        (match.implementation_family, match.implementation_version)
        for match in implementation.matches
    }))
    selected_references = set(deployment.matching_source_references)
    deployment_lineages = tuple(sorted({
        (source.implementation_family, source.implementation_version)
        for source in sources
        if source.source_reference in selected_references
        and (source.chain, source.address, source.contract_role) == (
            deployment.chain, deployment.address, deployment.contract_role,
        )
    }))

    if deployment.verdict == "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT":
        verdict = "REFERENCE_SOURCE_LINEAGE_CONFLICT"
    elif (
        implementation.verdict != "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
        or deployment.verdict == "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"
        or not deployment_lineages
    ):
        verdict = "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"
    elif set(implementation_lineages) & set(deployment_lineages):
        verdict = "REFERENCE_SOURCE_LINEAGE_ALIGNED"
    else:
        verdict = "REFERENCE_SOURCE_LINEAGE_CONFLICT"

    return ReferenceSourceAlignmentAssessment(
        contract_role=implementation.expected_role,
        implementation_lineages=implementation_lineages,
        deployment_lineages=deployment_lineages,
        verdict=verdict,
        status="UNVERIFIED_REFERENCE_SOURCE_ALIGNMENT_ASSESSMENT",
        limitations=(
            "SOURCE_LINEAGE_ALIGNMENT_DOES_NOT_PROVE_DEPLOYMENT_ORIGIN",
            "SOURCE_LINEAGE_ALIGNMENT_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "SOURCE_LINEAGE_ALIGNMENT_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "SOURCE_LINEAGE_ALIGNMENT_DEPENDS_ON_PINNED_SOURCE_CATALOG_COVERAGE",
        ),
    )
