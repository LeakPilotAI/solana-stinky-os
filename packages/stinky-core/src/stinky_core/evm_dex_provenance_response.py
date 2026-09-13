"""JSON-compatible API response contract for DEX provenance snapshots."""
from __future__ import annotations

from typing import Iterable, TypeAlias

from .evm_dex_provenance_snapshot import (
    DexProvenanceExplanationSnapshot,
    snapshot_dex_provenance_from_record,
)
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource

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


def serialize_dex_provenance_from_record(
    record: ReferenceDexEvidenceRecord,
    sources: Iterable[DexReferenceContractSource],
) -> DexProvenanceResponse:
    """Compose the existing record-backed snapshot and serialize it without new semantics."""
    snapshot = snapshot_dex_provenance_from_record(record, sources)
    return serialize_dex_provenance_snapshot(snapshot)
