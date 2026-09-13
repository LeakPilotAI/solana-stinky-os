"""Postgres-backed provider for preserved, typed DEX provenance evidence."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_core.evm_dex_provenance_codec import (
    decode_reference_dex_evidence_record,
    decode_reference_sources,
    validate_record_identity,
)

from stinky_api.dex_provenance import DexProvenanceEvidenceBundle
from stinky_api.dex_provenance_store import load_latest_dex_provenance_evidence


class PostgresDexProvenanceEvidenceProvider:
    """Hydrate only explicitly versioned provenance evidence persisted by Genesis."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(
        self,
        *,
        chain: str,
        pool_address: str,
    ) -> DexProvenanceEvidenceBundle | None:
        persisted = await load_latest_dex_provenance_evidence(
            self._session,
            chain=chain,
            pool_address=pool_address,
        )
        if persisted is None:
            return None

        record = decode_reference_dex_evidence_record(persisted.record_payload)
        sources = decode_reference_sources(persisted.sources_payload)
        if not sources:
            raise ValueError("persisted DEX provenance sources are empty")

        validate_record_identity(
            record,
            chain=persisted.chain,
            pool_address=persisted.pool_address,
            evidence_block=persisted.evidence_block,
        )
        if chain != persisted.chain or pool_address != persisted.pool_address:
            raise ValueError("persisted DEX provenance request identity mismatch")
        if persisted.chain not in {source.chain for source in sources}:
            raise ValueError("persisted DEX provenance sources do not cover requested chain")

        return DexProvenanceEvidenceBundle(record=record, sources=sources)
