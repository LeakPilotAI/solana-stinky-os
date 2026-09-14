"""Collection seam from complete observed DEX evidence to typed append-only persistence.

This module does not collect RPC data itself. It accepts already-observed, complete
historical evidence, composes the canonical #223 record once, and persists that
exact record with the exact pinned reference-source tuple through the #246 writer.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.dex_provenance_writer import persist_dex_provenance_evidence
from stinky_core.evm_contract_code import ContractCodeEvidence
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence
from stinky_core.evm_reference_dex_record import (
    ReferenceDexEvidenceRecord,
    compose_reference_dex_evidence_record,
)
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource
from stinky_core.evm_reference_materialization import ReferenceFingerprintBundle


@dataclass(frozen=True, slots=True)
class PersistedReferenceDexEvidence:
    record: ReferenceDexEvidenceRecord
    row_id: int


def _validate_source_bundle(
    bundle: ReferenceFingerprintBundle,
    sources: tuple[DexReferenceContractSource, ...],
) -> None:
    if not isinstance(sources, tuple):
        raise ValueError("DEX provenance collection sources must be an immutable tuple")
    if not sources:
        raise ValueError("DEX provenance collection sources must not be empty")
    references = tuple(sorted(source.source_reference for source in sources))
    if references != bundle.source_references:
        raise ValueError("DEX provenance collection sources do not match fingerprint bundle provenance")


async def compose_and_persist_dex_provenance_evidence(
    session: AsyncSession,
    *,
    relationship: FactoryRelationshipEvidence,
    factory_code: ContractCodeEvidence,
    pool_code: ContractCodeEvidence,
    router_code: ContractCodeEvidence,
    bundle: ReferenceFingerprintBundle,
    sources: tuple[DexReferenceContractSource, ...],
) -> PersistedReferenceDexEvidence:
    """Persist only after the canonical complete record composes successfully."""
    _validate_source_bundle(bundle, sources)
    record = compose_reference_dex_evidence_record(
        relationship,
        factory_code,
        pool_code,
        router_code,
        bundle,
    )
    row_id = await persist_dex_provenance_evidence(
        session,
        record=record,
        sources=sources,
    )
    return PersistedReferenceDexEvidence(record=record, row_id=row_id)
