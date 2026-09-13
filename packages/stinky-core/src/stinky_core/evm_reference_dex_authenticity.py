"""Conservative authenticity assessment for a complete reference DEX evidence record."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_reference_dex_record import ReferenceDexEvidenceRecord

_EXACT = "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
_RELATIONSHIP_MATCH = "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"
_FAMILY_CONSISTENT = "DEX_IMPLEMENTATION_FAMILY_CONSISTENT"
_KNOWN_RELATIONSHIP_CONFLICTS = frozenset({
    "FACTORY_LOOKUP_REPORTS_NO_POOL",
    "FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL",
})


@dataclass(frozen=True, slots=True)
class ReferenceDexAuthenticityAssessment:
    factory: str
    pool: str
    router: str
    relationship: str
    dex_family: str
    verdict: str
    status: str
    limitations: tuple[str, ...]


def assess_reference_dex_authenticity(
    record: ReferenceDexEvidenceRecord,
) -> ReferenceDexAuthenticityAssessment:
    """Assess whether observed components match the pinned reference evidence.

    REFERENCE_COMPONENTS_MATCH means only that all three historical runtime-code
    fingerprints exactly match materialized pinned-reference entries, the historical
    factory lookup confirms the discovered pool, and the composed implementation
    family is consistent. It is deliberately not a safety or deployment-origin claim.
    """
    envelope = record.envelope
    factory = envelope.factory_fingerprint.verdict
    pool = envelope.pool_fingerprint.verdict
    router = envelope.router_fingerprint.verdict
    relationship = record.relationship.relationship
    dex_family = envelope.dex_family.verdict

    component_verdicts = (factory, pool, router)
    if (
        component_verdicts == (_EXACT, _EXACT, _EXACT)
        and relationship == _RELATIONSHIP_MATCH
        and dex_family == _FAMILY_CONSISTENT
    ):
        verdict = "REFERENCE_DEX_COMPONENTS_MATCH"
    elif (
        relationship in _KNOWN_RELATIONSHIP_CONFLICTS
        or dex_family == "DEX_IMPLEMENTATION_FAMILY_CONFLICT"
    ):
        verdict = "REFERENCE_DEX_COMPONENT_EVIDENCE_CONFLICT"
    elif (
        "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT" in component_verdicts
        or "UNKNOWN_IMPLEMENTATION_FINGERPRINT" in component_verdicts
        or relationship == "UNKNOWN_FACTORY_RELATIONSHIP"
        or dex_family == "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"
    ):
        verdict = "UNKNOWN_REFERENCE_DEX_AUTHENTICITY"
    else:
        verdict = "REFERENCE_DEX_COMPONENT_EVIDENCE_CONFLICT"

    return ReferenceDexAuthenticityAssessment(
        factory=factory,
        pool=pool,
        router=router,
        relationship=relationship,
        dex_family=dex_family,
        verdict=verdict,
        status="UNVERIFIED_REFERENCE_DEX_AUTHENTICITY_ASSESSMENT",
        limitations=(
            "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_DEPLOYMENT_ORIGIN",
            "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "REFERENCE_COMPONENT_MATCH_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "REFERENCE_COMPONENT_MATCH_IS_HISTORICAL_BLOCK_SCOPED",
        ),
    )
