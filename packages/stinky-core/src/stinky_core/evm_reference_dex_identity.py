"""Compose implementation-match and deployment-identity assessments without conflation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_reference_deployment_identity import (
    ReferenceDeploymentIdentityAssessment,
    assess_reference_deployment_address,
)
from .evm_reference_dex_authenticity import (
    ReferenceDexAuthenticityAssessment,
    assess_reference_dex_authenticity,
)
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource

_MATCH = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"
_CONFLICT = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"
_UNKNOWN = "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"


@dataclass(frozen=True, slots=True)
class ReferenceDexIdentityAssessment:
    implementation: ReferenceDexAuthenticityAssessment
    factory_deployment: ReferenceDeploymentIdentityAssessment
    pool_deployment: ReferenceDeploymentIdentityAssessment
    router_deployment: ReferenceDeploymentIdentityAssessment
    verdict: str
    status: str
    limitations: tuple[str, ...]


def compose_reference_dex_identity(
    implementation: ReferenceDexAuthenticityAssessment,
    factory_deployment: ReferenceDeploymentIdentityAssessment,
    pool_deployment: ReferenceDeploymentIdentityAssessment,
    router_deployment: ReferenceDeploymentIdentityAssessment,
) -> ReferenceDexIdentityAssessment:
    """Combine distinct identity dimensions without inventing missing evidence."""
    deployments = (factory_deployment, pool_deployment, router_deployment)
    if len({item.chain for item in deployments}) != 1:
        raise ValueError("deployment identity assessments must share a chain")
    if (
        factory_deployment.contract_role != "FACTORY"
        or pool_deployment.contract_role != "POOL"
        or router_deployment.contract_role != "ROUTER"
    ):
        raise ValueError("deployment identity assessments must use FACTORY, POOL, ROUTER roles")

    deployment_verdicts = tuple(item.verdict for item in deployments)
    if (
        implementation.verdict == "REFERENCE_DEX_COMPONENT_EVIDENCE_CONFLICT"
        or _CONFLICT in deployment_verdicts
    ):
        verdict = "REFERENCE_DEX_IDENTITY_CONFLICT"
    elif (
        implementation.verdict == "UNKNOWN_REFERENCE_DEX_AUTHENTICITY"
        or _UNKNOWN in deployment_verdicts
    ):
        verdict = "UNKNOWN_REFERENCE_DEX_IDENTITY"
    elif (
        implementation.verdict == "REFERENCE_DEX_COMPONENTS_MATCH"
        and factory_deployment.verdict == _MATCH
        and router_deployment.verdict == _MATCH
        and pool_deployment.verdict == _MATCH
    ):
        verdict = "REFERENCE_DEX_IDENTITY_CONFIRMED"
    else:
        verdict = "UNKNOWN_REFERENCE_DEX_IDENTITY"

    return ReferenceDexIdentityAssessment(
        implementation=implementation,
        factory_deployment=factory_deployment,
        pool_deployment=pool_deployment,
        router_deployment=router_deployment,
        verdict=verdict,
        status="UNVERIFIED_REFERENCE_DEX_IDENTITY_ASSESSMENT",
        limitations=(
            "DEX_IDENTITY_ASSESSMENT_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "DEX_IDENTITY_ASSESSMENT_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "DEX_IDENTITY_ASSESSMENT_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "DEX_IDENTITY_CONFIRMATION_REQUIRES_EXPLICIT_DEPLOYMENT_IDENTITY_FOR_EACH_COMPONENT",
        ),
    )


def compose_reference_dex_identity_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> ReferenceDexIdentityAssessment:
    """Compose identity directly from preserved record addresses and pinned sources."""
    source_items = tuple(sources)
    envelope = record.envelope
    factory = envelope.factory_fingerprint
    pool = envelope.pool_fingerprint
    router = envelope.router_fingerprint

    implementation = assess_reference_dex_authenticity(record)
    factory_deployment = assess_reference_deployment_address(
        factory.chain, factory.address, source_items, expected_role="FACTORY"
    )
    pool_deployment = assess_reference_deployment_address(
        pool.chain, pool.address, source_items, expected_role="POOL"
    )
    router_deployment = assess_reference_deployment_address(
        router.chain, router.address, source_items, expected_role="ROUTER"
    )
    return compose_reference_dex_identity(
        implementation,
        factory_deployment,
        pool_deployment,
        router_deployment,
    )
