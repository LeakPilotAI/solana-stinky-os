"""Typed append-only persistence composition for DEX provenance evidence."""
from __future__ import annotations

from hashlib import sha256
import json

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.dex_provenance_store import append_dex_provenance_evidence
from stinky_core.evm_dex_provenance_codec import (
    encode_reference_dex_evidence_record,
    encode_reference_sources,
    validate_record_identity,
)
from stinky_core.evm_reference_dex_record import ReferenceDexEvidenceRecord
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource


def dex_provenance_evidence_key(
    record: ReferenceDexEvidenceRecord,
    sources: tuple[DexReferenceContractSource, ...],
) -> str:
    """Derive a deterministic content key from the exact typed provenance payloads."""
    if not isinstance(sources, tuple):
        raise ValueError("DEX provenance sources must be an immutable tuple")
    if not sources:
        raise ValueError("DEX provenance sources must not be empty")
    record_payload = encode_reference_dex_evidence_record(record)
    sources_payload = encode_reference_sources(sources)
    canonical = json.dumps(
        {"record": record_payload, "sources": list(sources_payload)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()


async def persist_dex_provenance_evidence(
    session: AsyncSession,
    *,
    record: ReferenceDexEvidenceRecord,
    sources: tuple[DexReferenceContractSource, ...],
) -> int:
    """Encode and append one exact evidence record without synthesizing any provenance."""
    if not isinstance(sources, tuple):
        raise ValueError("DEX provenance sources must be an immutable tuple")
    if not sources:
        raise ValueError("DEX provenance sources must not be empty")

    relationship = record.relationship
    chain = relationship.chain
    pool_address = relationship.pool_address
    evidence_block = relationship.block_number
    validate_record_identity(
        record,
        chain=chain,
        pool_address=pool_address,
        evidence_block=evidence_block,
    )
    if chain not in {source.chain for source in sources}:
        raise ValueError("DEX provenance sources do not cover record chain")

    record_payload = encode_reference_dex_evidence_record(record)
    sources_payload = encode_reference_sources(sources)
    evidence_key = dex_provenance_evidence_key(record, sources)

    return await append_dex_provenance_evidence(
        session,
        chain=chain,
        pool_address=pool_address,
        evidence_block=evidence_block,
        evidence_key=evidence_key,
        record_payload=record_payload,
        sources_payload=sources_payload,
    )
