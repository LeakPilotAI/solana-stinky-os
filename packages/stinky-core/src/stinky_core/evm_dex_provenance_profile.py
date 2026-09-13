"""Conservative DEX provenance profile over strict lineage and pool evidence tier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_pool_deployment_evidence_tier import (
    PoolDeploymentEvidenceTierAssessment,
    assess_pool_deployment_evidence_tier_from_record,
)
from .evm_reference_dex_lineage import (
    ReferenceDexLineageAssessment,
    compose_reference_dex_lineage_from_record,
)
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource


@dataclass(frozen=True, slots=True)
class DexProvenanceProfile:
    strict_lineage: ReferenceDexLineageAssessment
    pool_evidence_tier: PoolDeploymentEvidenceTierAssessment
    profile: str
    verdict: str
    status: str
    limitations: tuple[str, ...]


def compose_dex_provenance_profile(
    strict_lineage: ReferenceDexLineageAssessment,
    pool_evidence_tier: PoolDeploymentEvidenceTierAssessment,
) -> DexProvenanceProfile:
    """Expose strict pinned lineage and pool evidence tier without conflation."""
    pool_deployment = strict_lineage.identity.pool_deployment
    if pool_deployment.chain != pool_evidence_tier.chain:
        raise ValueError("DEX provenance inputs must share a chain")
    if pool_deployment.address != pool_evidence_tier.pool_address:
        raise ValueError("DEX provenance inputs must share a pool address")

    strict_verdict = strict_lineage.verdict
    pool_verdict = pool_evidence_tier.verdict

    if (
        strict_verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT"
        or pool_verdict == "POOL_DEPLOYMENT_EVIDENCE_CONFLICT"
    ):
        profile = "DEX_PROVENANCE_CONFLICT"
        verdict = "DEX_PROVENANCE_CONFLICT"
    elif strict_verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED":
        if pool_verdict != "EXTERNALLY_PINNED_POOL_DEPLOYMENT_MATCH":
            raise ValueError("strict DEX lineage confirmation requires externally pinned pool evidence")
        profile = "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE"
        verdict = "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED"
    elif pool_verdict == "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY":
        profile = "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE"
        verdict = "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE"
    elif (
        strict_verdict == "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"
        and pool_verdict == "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE"
    ):
        profile = "UNKNOWN_DEX_PROVENANCE_PROFILE"
        verdict = "UNKNOWN_DEX_PROVENANCE_PROFILE"
    else:
        raise ValueError("unsupported DEX provenance evidence combination")

    return DexProvenanceProfile(
        strict_lineage=strict_lineage,
        pool_evidence_tier=pool_evidence_tier,
        profile=profile,
        verdict=verdict,
        status="UNVERIFIED_DEX_PROVENANCE_PROFILE",
        limitations=(
            "FACTORY_ATTESTED_POOL_EVIDENCE_DOES_NOT_UPGRADE_STRICT_DEX_IDENTITY",
            "DEX_PROVENANCE_PROFILE_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "DEX_PROVENANCE_PROFILE_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "DEX_PROVENANCE_PROFILE_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "DEX_PROVENANCE_PROFILE_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "DEX_PROVENANCE_PROFILE_IS_NOT_AN_EXECUTION_AUTHORIZATION",
        ),
    )


def compose_dex_provenance_profile_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> DexProvenanceProfile:
    """Build both provenance views from the same preserved record and source catalog."""
    source_items = tuple(sources)
    strict = compose_reference_dex_lineage_from_record(record, source_items)
    pool_tier = assess_pool_deployment_evidence_tier_from_record(record, source_items)
    return compose_dex_provenance_profile(strict, pool_tier)
