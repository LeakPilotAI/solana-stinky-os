"""Persistent, idempotent deployer launch history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings


class LaunchHistoryStore:
    """Persist launch observations and later attach measured outcomes."""

    def __init__(self, database_url: str | None = None) -> None:
        self._engine = create_async_engine(
            database_url or settings.database_url,
            pool_pre_ping=True,
            pool_size=3,
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_schema(self) -> None:
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "migrations" / "002_entity_launch_history.sql"
        if not path.exists():
            raise FileNotFoundError(f"launch history migration missing: {path}")
        sql = path.read_text(encoding="utf-8")
        async with self._sessions() as session:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await session.execute(text(statement))
            await session.commit()

    async def record_launch(
        self,
        *,
        entity_id: UUID,
        deployer_wallet: str,
        event_id: str,
        mint: str | None = None,
        observed_at: datetime | None = None,
    ) -> bool:
        """Record a launch and increment its entity count exactly once."""
        observed = observed_at or datetime.now(timezone.utc)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO entity_launches (
                            entity_id, deployer_wallet, mint, event_id, observed_at
                        ) VALUES (
                            :eid, :wallet, :mint, :event_id, :observed_at
                        )
                        ON CONFLICT DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "eid": entity_id,
                        "wallet": deployer_wallet,
                        "mint": mint,
                        "event_id": event_id,
                        "observed_at": observed,
                    },
                )
            ).first()
            if not row:
                await session.rollback()
                return False

            await session.execute(
                text(
                    """
                    UPDATE entities
                    SET launch_count = launch_count + 1, updated_at = now()
                    WHERE entity_id = :eid
                    """
                ),
                {"eid": entity_id},
            )
            await session.commit()
            return True

    async def list_entity_launches(
        self,
        *,
        entity_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return persistent launch and measured-outcome evidence for an entity."""
        bounded_limit = max(1, min(limit, 500))
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, entity_id, deployer_wallet, mint, event_id,
                               observed_at, outcome_status, outcome_meta, created_at
                        FROM entity_launches
                        WHERE entity_id = :eid
                        ORDER BY observed_at DESC, id DESC
                        LIMIT :limit
                        """
                    ),
                    {"eid": entity_id, "limit": bounded_limit},
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def list_deployer_launches(
        self,
        *,
        deployer_wallet: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return persistent launch and measured-outcome evidence for a deployer wallet."""
        bounded_limit = max(1, min(limit, 500))
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, entity_id, deployer_wallet, mint, event_id,
                               observed_at, outcome_status, outcome_meta, created_at
                        FROM entity_launches
                        WHERE deployer_wallet = :wallet
                        ORDER BY observed_at DESC, id DESC
                        LIMIT :limit
                        """
                    ),
                    {"wallet": deployer_wallet, "limit": bounded_limit},
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def get_deployer_history_summary(
        self,
        *,
        deployer_wallet: str,
    ) -> dict[str, Any]:
        """Return evidence counts and temporal bounds without inventing outcomes."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*)::int AS launch_count,
                            COUNT(*) FILTER (WHERE outcome_status IS NOT NULL)::int AS outcomes_known,
                            COUNT(*) FILTER (WHERE outcome_status = 'completed')::int AS completed_count,
                            COUNT(*) FILTER (WHERE outcome_status IS NULL)::int AS outcomes_unknown,
                            MIN(observed_at) AS first_launch_at,
                            MAX(observed_at) AS last_launch_at
                        FROM entity_launches
                        WHERE deployer_wallet = :wallet
                        """
                    ),
                    {"wallet": deployer_wallet},
                )
            ).mappings().first()
            if not row:
                return {
                    "deployer_wallet": deployer_wallet,
                    "launch_count": 0,
                    "outcomes_known": 0,
                    "completed_count": 0,
                    "outcomes_unknown": 0,
                    "first_launch_at": None,
                    "last_launch_at": None,
                }
            result = dict(row)
            result["deployer_wallet"] = deployer_wallet
            return result

    async def record_outcome(
        self,
        *,
        mint: str,
        status: str,
        metadata: dict[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> bool:
        """Attach an observed lifecycle outcome to a known launch.

        Returns True only when a matching launch exists and its stored outcome
        changes. Unknown mints are deliberately ignored so missing evidence is
        never converted into a fabricated developer outcome.
        """
        if not mint or not status:
            return False
        observed = observed_at or datetime.now(timezone.utc)
        import orjson

        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE entity_launches
                    SET outcome_status = :status,
                        outcome_meta = CAST(:metadata AS jsonb),
                        created_at = created_at
                    WHERE mint = :mint
                      AND (
                          outcome_status IS DISTINCT FROM :status
                          OR outcome_meta IS DISTINCT FROM CAST(:metadata AS jsonb)
                      )
                    RETURNING id
                    """
                ),
                {
                    "status": status,
                    "metadata": orjson.dumps(
                        {**(metadata or {}), "observed_at": observed.isoformat()}
                    ).decode(),
                    "mint": mint,
                },
            )
            row = result.first()
            if not row:
                await session.rollback()
                return False
            await session.commit()
            return True
