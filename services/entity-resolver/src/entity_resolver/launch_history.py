"""Persistent, idempotent deployer launch history."""

from __future__ import annotations

from datetime import datetime, timezone
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
