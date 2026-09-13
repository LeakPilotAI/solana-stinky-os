"""JSON-compatible API response contract for DEX provenance snapshots."""
from __future__ import annotations

from typing import TypeAlias

from .evm_dex_provenance_snapshot import DexProvenanceExplanationSnapshot

DexProvenanceResponse: TypeAlias = dict[str, str | list[str]]


def serialize_dex_provenance_snapshot(
    snapshot: DexProvenanceExplanationSnapshot,
) -> DexProvenanceResponse:
    """Serialize stable provenance fields without exposing internal evidence objects."""
    return {
        "category": snapshot.category,
        "profile_verdict": snapshot.profile_verdict,
        "strict_lineage_verdict": snapshot.strict_lineage_verdict,
        "pool_evidence_tier_verdict": snapshot.pool_evidence_tier_verdict,
        "factory_attestation_verdict": snapshot.factory_attestation_verdict,
        "status": snapshot.status,
        "limitations": list(snapshot.limitations),
    }
