"""Append-only Postgres repository for preserved DEX provenance evidence payloads.

Persistence is deliberately evidence-only. This module does not reconstruct core evidence objects,
score provenance, or authorize admission/execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PersistedDexProvenanceEvidence:
    id: int
    chain: str
    pool_address: str
    evidence_block: int
    evidence_key: str
    record_payload: Mapping[str, Any]
    sources_payload: tuple[Mapping[str, Any], ...]
    observed_at: datetime


def _identity(chain: str, pool_address: str) -> tuple[str, str]:
    normalized_chain = str(chain or "").strip()
    normalized_pool = str(pool_address or "").strip()
    if not normalized_chain:
        raise ValueError("chain required")
    if not normalized_pool:
        raise ValueError("pool_address required")
    return normalized_chain, normalized_pool


async def append_dex_provenance_evidence(
    session: AsyncSession,
    *,
    chain: str,
    pool_address: str,
    evidence_block: int,
    evidence_key: str,
    record_payload: Mapping[str, Any],
    sources_payload: Sequence[Mapping[str, Any]],
) -> int:
    """Append one preserved evidence snapshot and return its row id."""
    normalized_chain, normalized_pool = _identity(chain, pool_address)
    block = int(evidence_block)
    if block < 0:
        raise ValueError("evidence_block must be non-negative")
    key = str(evidence_key or "").strip()
    if not key:
        raise ValueError("evidence_key required")
    if not isinstance(record_payload, Mapping):
        raise ValueError("record_payload must be a mapping")
    if isinstance(sources_payload, (str, bytes)):
        raise ValueError("sources_payload must be a sequence of mappings")
    sources = list(sources_payload)
    if any(not isinstance(item, Mapping) for item in sources):
        raise ValueError("sources_payload entries must be mappings")

    stmt = text(
        """
        INSERT INTO dex_provenance_evidence_snapshots
            (chain, pool_address, evidence_block, evidence_key, record_payload, sources_payload)
        VALUES
            (:chain, :pool_address, :evidence_block, :evidence_key,
             CAST(:record_payload AS JSONB), CAST(:sources_payload AS JSONB))
        ON CONFLICT (chain, pool_address, evidence_block, evidence_key) DO NOTHING
        RETURNING id
        """
    )
    import json

    result = await session.execute(
        stmt,
        {
            "chain": normalized_chain,
            "pool_address": normalized_pool,
            "evidence_block": block,
            "evidence_key": key,
            "record_payload": json.dumps(dict(record_payload), sort_keys=True, separators=(",", ":")),
            "sources_payload": json.dumps([dict(item) for item in sources], sort_keys=True, separators=(",", ":")),
        },
    )
    row_id = result.scalar_one_or_none()
    if row_id is not None:
        return int(row_id)

    existing = await session.execute(
        text(
            """
            SELECT id FROM dex_provenance_evidence_snapshots
            WHERE chain = :chain AND pool_address = :pool_address
              AND evidence_block = :evidence_block AND evidence_key = :evidence_key
            """
        ),
        {
            "chain": normalized_chain,
            "pool_address": normalized_pool,
            "evidence_block": block,
            "evidence_key": key,
        },
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is None:
        raise RuntimeError("DEX provenance evidence append did not persist")
    return int(existing_id)


async def load_latest_dex_provenance_evidence(
    session: AsyncSession,
    *,
    chain: str,
    pool_address: str,
) -> PersistedDexProvenanceEvidence | None:
    """Load the newest preserved snapshot for one exact chain/pool identity."""
    normalized_chain, normalized_pool = _identity(chain, pool_address)
    result = await session.execute(
        text(
            """
            SELECT id, chain, pool_address, evidence_block, evidence_key,
                   record_payload, sources_payload, observed_at
            FROM dex_provenance_evidence_snapshots
            WHERE chain = :chain AND pool_address = :pool_address
            ORDER BY evidence_block DESC, id DESC
            LIMIT 1
            """
        ),
        {"chain": normalized_chain, "pool_address": normalized_pool},
    )
    row = result.mappings().first()
    if row is None:
        return None
    sources = row["sources_payload"]
    if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
        raise ValueError("persisted DEX provenance sources are malformed")
    record = row["record_payload"]
    if not isinstance(record, dict):
        raise ValueError("persisted DEX provenance record is malformed")
    return PersistedDexProvenanceEvidence(
        id=int(row["id"]),
        chain=str(row["chain"]),
        pool_address=str(row["pool_address"]),
        evidence_block=int(row["evidence_block"]),
        evidence_key=str(row["evidence_key"]),
        record_payload=record,
        sources_payload=tuple(sources),
        observed_at=row["observed_at"],
    )
