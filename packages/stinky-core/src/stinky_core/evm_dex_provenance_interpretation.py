"""Descriptive, non-execution interpretation of a DEX provenance profile."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_dex_provenance_profile import DexProvenanceProfile


@dataclass(frozen=True, slots=True)
class DexProvenanceInterpretation:
    provenance_profile: DexProvenanceProfile
    category: str
    status: str
    limitations: tuple[str, ...]


def interpret_dex_provenance(
    provenance_profile: DexProvenanceProfile,
) -> DexProvenanceInterpretation:
    """Classify provenance strength without changing any underlying verdict."""
    verdict = provenance_profile.verdict

    if verdict == "DEX_PROVENANCE_CONFLICT":
        category = "CONFLICTED_PROVENANCE"
    elif verdict == "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED":
        category = "STRICT_PINNED_PROVENANCE"
    elif verdict == "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE":
        category = "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED"
    elif verdict == "UNKNOWN_DEX_PROVENANCE_PROFILE":
        category = "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"
    else:
        raise ValueError("unsupported DEX provenance profile verdict")

    return DexProvenanceInterpretation(
        provenance_profile=provenance_profile,
        category=category,
        status="DESCRIPTIVE_NON_EXECUTION_PROVENANCE_INTERPRETATION",
        limitations=(
            "PROVENANCE_INTERPRETATION_DOES_NOT_MODIFY_UNDERLYING_VERDICTS",
            "PROVENANCE_INTERPRETATION_IS_NOT_A_TOKEN_OR_DEX_SAFETY_DECISION",
            "PROVENANCE_INTERPRETATION_IS_NOT_AN_ADMISSION_DECISION",
            "PROVENANCE_INTERPRETATION_IS_NOT_AN_OPPORTUNITY_SCORE",
            "PROVENANCE_INTERPRETATION_IS_NOT_AN_EXECUTION_AUTHORIZATION",
        ),
    )
