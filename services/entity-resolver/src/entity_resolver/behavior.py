"""Descriptive behavioral fingerprints from observed entity launch history."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any
from uuid import UUID

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings


def _as_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def cadence_bucket(median_interval_sec: float | None) -> str:
    """Describe observed launch cadence without assigning quality or risk."""
    if median_interval_sec is None:
        return "unknown"
    if median_interval_sec <= 3600:
        return "high_frequency"
    if median_interval_sec <= 86400:
        return "active"
    if median_interval_sec <= 604800:
        return "recurring"
    return "sparse"


def build_behavioral_fingerprint(launches: list[dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic, descriptive evidence from persistent launch rows."""
    timestamps = sorted(
        ts for ts in (_as_timestamp(row.get("observed_at")) for row in launches) if ts is not None
    )
    intervals = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:])
        if (later - earlier).total_seconds() >= 0
    ]
    median_interval = float(median(intervals)) if intervals else None

    known = sum(1 for row in launches if row.get("outcome_status") is not None)
    completed = sum(1 for row in launches if row.get("outcome_status") == "completed")
    unknown = len(launches) - known
    coverage = (known / len(launches)) if launches else None

    return {
        "launch_count": len(launches),
        "outcomes_known": known,
        "completed_count": completed,
        "outcomes_unknown": unknown,
        "outcome_coverage": coverage,
        "first_launch_at": timestamps[0].isoformat() if timestamps else None,
        "last_launch_at": timestamps[-1].isoformat() if timestamps else None,
        "median_launch_interval_sec": median_interval,
        "cadence_bucket": cadence_bucket(median_interval),
        "evidence_basis": "entity_launches",
    }


class BehaviorFingerprintStore:
    """Persist the latest descriptive fingerprint for each entity."""

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

        path = Path(__file__).resolve().parents[2] / "migrations" / "003_entity_behavior_fingerprints.sql"
        if not path.exists():
            raise FileNotFoundError(f"behavior fingerprint migration missing: {path}")
        sql = path.read_text(encoding="utf-8")
        async with self._sessions() as session:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await session.execute(text(statement))
            await session.commit()

    async def _launches_for_entity(self, entity_id: UUID) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT observed_at, outcome_status
                        FROM entity_launches
                        WHERE entity_id = :eid
                        ORDER BY observed_at ASC, id ASC
                        LIMIT 5000
                        """
                    ),
                    {"eid": entity_id},
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def refresh_entity(self, entity_id: UUID) -> dict[str, Any]:
        """Recompute from stored observations; never infer missing outcomes."""
        launches = await self._launches_for_entity(entity_id)
        fingerprint = build_behavioral_fingerprint(launches)
        computed_at = datetime.now(timezone.utc)
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO entity_behavior_fingerprints (
                        entity_id, launch_count, outcomes_known, completed_count,
                        outcomes_unknown, first_launch_at, last_launch_at,
                        median_launch_interval_sec, cadence_bucket, fingerprint, computed_at
                    ) VALUES (
                        :eid, :launch_count, :outcomes_known, :completed_count,
                        :outcomes_unknown, :first_launch_at, :last_launch_at,
                        :median_interval, :cadence, CAST(:fingerprint AS jsonb), :computed_at
                    )
                    ON CONFLICT (entity_id) DO UPDATE SET
                        launch_count = EXCLUDED.launch_count,
                        outcomes_known = EXCLUDED.outcomes_known,
                        completed_count = EXCLUDED.completed_count,
                        outcomes_unknown = EXCLUDED.outcomes_unknown,
                        first_launch_at = EXCLUDED.first_launch_at,
                        last_launch_at = EXCLUDED.last_launch_at,
                        median_launch_interval_sec = EXCLUDED.median_launch_interval_sec,
                        cadence_bucket = EXCLUDED.cadence_bucket,
                        fingerprint = EXCLUDED.fingerprint,
                        computed_at = EXCLUDED.computed_at
                    """
                ),
                {
                    "eid": entity_id,
                    "launch_count": fingerprint["launch_count"],
                    "outcomes_known": fingerprint["outcomes_known"],
                    "completed_count": fingerprint["completed_count"],
                    "outcomes_unknown": fingerprint["outcomes_unknown"],
                    "first_launch_at": _as_timestamp(fingerprint["first_launch_at"]),
                    "last_launch_at": _as_timestamp(fingerprint["last_launch_at"]),
                    "median_interval": fingerprint["median_launch_interval_sec"],
                    "cadence": fingerprint["cadence_bucket"],
                    "fingerprint": orjson.dumps(fingerprint).decode(),
                    "computed_at": computed_at,
                },
            )
            await session.commit()
        return fingerprint

    async def refresh_for_mint(self, mint: str) -> dict[str, Any] | None:
        """Refresh the entity fingerprint for a known launch mint."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text("SELECT entity_id FROM entity_launches WHERE mint = :mint LIMIT 1"),
                    {"mint": mint},
                )
            ).first()
        if not row:
            return None
        return await self.refresh_entity(row[0])
