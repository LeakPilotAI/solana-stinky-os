"""Deterministic evidence summary for DEX provenance interpretation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_dex_provenance_interpretation import (
    DexProvenanceInterpretation,
    interpret_dex_provenance,
)
from .evm_dex_provenance_profile import compose_dex_provenance_profile_from_record
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource


@dataclass(frozen=True, slots=True)
class DexProvenanceExplanation:
    interpretation: DexProvenanceInterpretation
    evidence_summary: tuple[str, ...]
    status: str
    limitations: tuple[str, ...]


def explain_dex_provenance(
    interpretation: DexProvenanceInterpretation,
) -> DexProvenanceExplanation:
    """Explain a provenance category using only preserved lower-layer verdicts."""
    profile = interpretation.provenance_profile
    strict_verdict = profile.strict_lineage.verdict
    pool_verdict = profile.pool_evidence_tier.verdict
    factory_verdict = profile.pool_evidence_tier.factory_attestation.verdict
    category = interpretation.category

    if category == "STRICT_PINNED_PROVENANCE":
        expected_profile = "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED"
    elif category == "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED":
        expected_profile = "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE"
    elif category == "CONFLICTED_PROVENANCE":
        expected_profile = "DEX_PROVENANCE_CONFLICT"
    elif category == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE":
        expected_profile = "UNKNOWN_DEX_PROVENANCE_PROFILE"
    else:
        raise ValueError("unsupported DEX provenance interpretation category")

    if profile.verdict != expected_profile:
        raise ValueError("DEX provenance interpretation does not match preserved profile verdict")

    return DexProvenanceExplanation(
        interpretation=interpretation,
        evidence_summary=(
            f"PROFILE_VERDICT={profile.verdict}",
            f"STRICT_LINEAGE_VERDICT={strict_verdict}",
            f"POOL_EVIDENCE_TIER_VERDICT={pool_verdict}",
            f"FACTORY_ATTESTATION_VERDICT={factory_verdict}",
        ),
        status="DESCRIPTIVE_PROVENANCE_EVIDENCE_SUMMARY",
        limitations=(
            "PROVENANCE_EXPLANATION_USES_ONLY_PRESERVED_EVIDENCE_VERDICTS",
            "PROVENANCE_EXPLANATION_DOES_NOT_INFER_OR_BACKFILL_PROVENANCE",
            "PROVENANCE_EXPLANATION_DOES_NOT_MODIFY_UNDERLYING_VERDICTS",
            "PROVENANCE_EXPLANATION_IS_NOT_A_TOKEN_OR_DEX_SAFETY_DECISION",
            "PROVENANCE_EXPLANATION_IS_NOT_AN_OPPORTUNITY_SCORE",
            "PROVENANCE_EXPLANATION_IS_NOT_AN_ADMISSION_DECISION",
            "PROVENANCE_EXPLANATION_IS_NOT_AN_EXECUTION_AUTHORIZATION",
        ),
    )


def explain_dex_provenance_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> DexProvenanceExplanation:
    """Compose record-backed profile, interpretation, and explanation without new semantics."""
    source_items = tuple(sources)
    profile = compose_dex_provenance_profile_from_record(record, source_items)
    interpretation = interpret_dex_provenance(profile)
    return explain_dex_provenance(interpretation)
