"""Read-only API service boundary for DEX provenance responses.

This module deliberately does not fabricate or reconstruct provenance evidence. A caller must
provide a real evidence provider capable of returning the preserved ReferenceDexEvidenceRecord
and pinned reference sources for the requested DEX context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from stinky_core.evm_dex_provenance_response import (
    DexProvenanceResponse,
    serialize_dex_provenance_from_record,
)
from stinky_core.evm_reference_dex_record import ReferenceDexEvidenceRecord
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource


@dataclass(frozen=True, slots=True)
class DexProvenanceEvidenceBundle:
    record: ReferenceDexEvidenceRecord
    sources: tuple[DexReferenceContractSource, ...]


class DexProvenanceEvidenceProvider(Protocol):
    """Read-only source of already-collected DEX provenance evidence."""

    async def load(
        self,
        *,
        chain: str,
        pool_address: str,
    ) -> DexProvenanceEvidenceBundle | None: ...


async def read_dex_provenance_response(
    provider: DexProvenanceEvidenceProvider,
    *,
    chain: str,
    pool_address: str,
) -> DexProvenanceResponse:
    """Return a transport-safe provenance response or fail closed when evidence is unavailable."""
    normalized_chain = str(chain or "").strip()
    normalized_pool = str(pool_address or "").strip()
    if not normalized_chain:
        raise ValueError("chain required")
    if not normalized_pool:
        raise ValueError("pool_address required")

    bundle = await provider.load(chain=normalized_chain, pool_address=normalized_pool)
    if bundle is None:
        raise LookupError("DEX provenance evidence unavailable")
    if not isinstance(bundle.sources, tuple):
        raise ValueError("DEX provenance sources must be an immutable tuple")

    return serialize_dex_provenance_from_record(bundle.record, bundle.sources)
