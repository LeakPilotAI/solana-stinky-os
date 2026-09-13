"""DEX-level source-lineage composition over existing reference identity evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_reference_dex_identity import ReferenceDexIdentityAssessment
from .evm_reference_source_alignment import ReferenceSourceAlignmentAssessment

_ALIGNED = "REFERENCE_SOURCE_LINEAGE_ALIGNED"
_CONFLICT = "REFERENCE_SOURCE_LINEAGE_CONFLICT"
_UNKNOWN = "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"


@dataclass(frozen=True, slots=True)
class ReferenceDexLineageAssessment:
    identity: ReferenceDexIdentityAssessment
    factory_alignment: ReferenceSourceAlignmentAssessment
    pool_alignment: ReferenceSourceAlignmentAssessment
    router_alignment: ReferenceSourceAlignmentAssessment
    verdict: str
    status: str
    limitations: tuple[str, ...]


def compose_reference_dex_lineage(
    identity: ReferenceDexIdentityAssessment,
    factory_alignment: ReferenceSourceAlignmentAssessment,
    pool_alignment: ReferenceSourceAlignmentAssessment,
    router_alignment: ReferenceSourceAlignmentAssessment,
) -> ReferenceDexLineageAssessment:
    """Gate DEX identity on explicit source-lineage agreement for all components."""
    alignments = (factory_alignment, pool_alignment, router_alignment)
    if (
        factory_alignment.contract_role != "FACTORY"
        or pool_alignment.contract_role != "POOL"
        or router_alignment.contract_role != "ROUTER"
    ):
        raise ValueError("source lineage assessments must use FACTORY, POOL, ROUTER roles")

    alignment_verdicts = tuple(item.verdict for item in alignments)
    if identity.verdict == "REFERENCE_DEX_IDENTITY_CONFLICT" or _CONFLICT in alignment_verdicts:
        verdict = "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT"
    elif identity.verdict != "REFERENCE_DEX_IDENTITY_CONFIRMED" or _UNKNOWN in alignment_verdicts:
        verdict = "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"
    elif alignment_verdicts == (_ALIGNED, _ALIGNED, _ALIGNED):
        verdict = "REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"
    else:
        verdict = "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"

    return ReferenceDexLineageAssessment(
        identity=identity,
        factory_alignment=factory_alignment,
        pool_alignment=pool_alignment,
        router_alignment=router_alignment,
        verdict=verdict,
        status="UNVERIFIED_REFERENCE_DEX_LINEAGE_ASSESSMENT",
        limitations=(
            "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "DEX_LINEAGE_IDENTITY_DEPENDS_ON_PINNED_SOURCE_CATALOG_COVERAGE",
        ),
    )
