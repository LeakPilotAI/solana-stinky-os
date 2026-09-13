"""Immutable transport snapshot for descriptive DEX provenance explanations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_dex_provenance_explanation import (
    DexProvenanceExplanation,
    explain_dex_provenance_from_record,
)
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource


@dataclass(frozen=True, slots=True)
class DexProvenanceExplanationSnapshot:
    explanation: DexProvenanceExplanation
    category: str
    profile_verdict: str
    strict_lineage_verdict: str
    pool_evidence_tier_verdict: str
    factory_attestation_verdict: str
    status: str
    limitations: tuple[str, ...]


def snapshot_dex_provenance_explanation(
    explanation: DexProvenanceExplanation,
) -> DexProvenanceExplanationSnapshot:
    """Project an explanation into stable transport fields without new inference."""
    interpretation = explanation.interpretation
    profile = interpretation.provenance_profile

    expected_summary = (
        f"PROFILE_VERDICT={profile.verdict}",
        f"STRICT_LINEAGE_VERDICT={profile.strict_lineage.verdict}",
        f"POOL_EVIDENCE_TIER_VERDICT={profile.pool_evidence_tier.verdict}",
        f"FACTORY_ATTESTATION_VERDICT={profile.pool_evidence_tier.factory_attestation.verdict}",
    )
    if explanation.evidence_summary != expected_summary:
        raise ValueError("DEX provenance explanation summary does not match preserved evidence")

    return DexProvenanceExplanationSnapshot(
        explanation=explanation,
        category=interpretation.category,
        profile_verdict=profile.verdict,
        strict_lineage_verdict=profile.strict_lineage.verdict,
        pool_evidence_tier_verdict=profile.pool_evidence_tier.verdict,
        factory_attestation_verdict=profile.pool_evidence_tier.factory_attestation.verdict,
        status=explanation.status,
        limitations=explanation.limitations,
    )


def snapshot_dex_provenance_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> DexProvenanceExplanationSnapshot:
    """Compose the existing record-backed explanation and snapshot it without new semantics."""
    source_items = tuple(sources)
    explanation = explain_dex_provenance_from_record(record, source_items)
    return snapshot_dex_provenance_explanation(explanation)
