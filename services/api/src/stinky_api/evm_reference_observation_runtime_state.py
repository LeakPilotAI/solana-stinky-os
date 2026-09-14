"""Durable non-execution state for reference DEX observation triggers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ReferenceDexObservationRuntimeState:
    chain: str
    pool_address: str
    last_completed_block: int
    last_completed_at: datetime


def _identity(chain: str, pool_address: str) -> tuple[str, str]:
    normalized_chain = str(chain or "").strip()
    normalized_pool = str(pool_address or "").strip()
    if not normalized_chain:
        raise ValueError("chain required")
    if not normalized_pool:
        raise ValueError("pool_address required")
    return normalized_chain, normalized_pool


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("completed_at must be timezone-aware")
    return value.astimezone(timezone.utc)


async def load_reference_observation_runtime_state(
    session: AsyncSession, *, chain: str, pool_address: str
) -> ReferenceDexObservationRuntimeState | None:
    chain, pool_address = _identity(chain, pool_address)
    result = await session.execute(
        text("""
            SELECT chain, pool_address, last_completed_block, last_completed_at
            FROM evm_reference_observation_trigger_state
            WHERE chain = :chain AND pool_address = :pool_address
        """),
        {"chain": chain, "pool_address": pool_address},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return ReferenceDexObservationRuntimeState(
        chain=str(row["chain"]), pool_address=str(row["pool_address"]),
        last_completed_block=int(row["last_completed_block"]),
        last_completed_at=row["last_completed_at"],
    )


async def record_reference_observation_completion(
    session: AsyncSession, *, chain: str, pool_address: str,
    block_number: int, completed_at: datetime,
) -> ReferenceDexObservationRuntimeState:
    chain, pool_address = _identity(chain, pool_address)
    if not isinstance(block_number, int) or isinstance(block_number, bool) or block_number < 0:
        raise ValueError("block_number must be a non-negative integer")
    completed_at = _aware_utc(completed_at)
    result = await session.execute(
        text("""
            INSERT INTO evm_reference_observation_trigger_state
                (chain, pool_address, last_completed_block, last_completed_at)
            VALUES (:chain, :pool_address, :block_number, :completed_at)
            ON CONFLICT (chain, pool_address) DO UPDATE SET
                last_completed_block = EXCLUDED.last_completed_block,
                last_completed_at = EXCLUDED.last_completed_at,
                updated_at = NOW()
            WHERE evm_reference_observation_trigger_state.last_completed_block < EXCLUDED.last_completed_block
            RETURNING chain, pool_address, last_completed_block, last_completed_at
        """),
        {"chain": chain, "pool_address": pool_address,
         "block_number": block_number, "completed_at": completed_at},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError("duplicate or replayed reference observation block")
    return ReferenceDexObservationRuntimeState(
        chain=str(row["chain"]), pool_address=str(row["pool_address"]),
        last_completed_block=int(row["last_completed_block"]),
        last_completed_at=row["last_completed_at"],
    )
