"""Descriptive behavioral fingerprints from observed entity and wallet history."""

from __future__ import annotations

from collections import Counter
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


def build_behavioral_fingerprint(
    launches: list[dict[str, Any]],
    *,
    wallets: list[dict[str, Any]] | None = None,
    early_buy_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic, descriptive evidence; missing evidence stays unknown."""
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

    wallet_rows = wallets or []
    role_counts = dict(sorted(Counter(str(row.get("role") or "unknown") for row in wallet_rows).items()))
    early_stats = early_buy_stats or {}

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
        "wallet_count": len(wallet_rows),
        "wallet_role_counts": role_counts,
        "early_buyer_wallet_count": early_stats.get("early_buyer_wallet_count"),
        "early_buyer_mint_count": early_stats.get("early_buyer_mint_count"),
        "repeat_early_buyer_wallet_count": early_stats.get("repeat_early_buyer_wallet_count"),
        "early_buyer_evidence": early_stats.get("evidence_basis", "unknown"),
        "evidence_basis": "entity_launches+entity_wallets+early_buyer_observations",
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

        migration_dir = Path(__file__).resolve().parents[2] / "migrations"
        for name in ("003_entity_behavior_fingerprints.sql", "004_entity_wallet_behavior.sql"):
            path = migration_dir / name
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

    async def _wallets_for_entity(self, entity_id: UUID) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, role, first_seen_at, last_seen_at
                        FROM entity_wallets
                        WHERE entity_id = :eid
                        ORDER BY role, wallet
                        """
                    ),
                    {"eid": entity_id},
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def _early_buy_stats(self, entity_id: UUID) -> dict[str, Any]:
        """Measure observed early-buyer participation for this entity's wallets.

        If the underlying observation table is unavailable, return unknown rather
        than pretending that no early-buyer activity exists.
        """
        async with self._sessions() as session:
            try:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT
                                COUNT(DISTINCT mb.wallet)::int AS early_buyer_wallet_count,
                                COUNT(DISTINCT mb.mint)::int AS early_buyer_mint_count,
                                COUNT(*) FILTER (WHERE wallet_counts.mint_count >= 2)::int
                                    AS repeat_early_buyer_wallet_count
                            FROM migration_buyers mb
                            JOIN entity_wallets ew ON ew.wallet = mb.wallet
                            LEFT JOIN (
                                SELECT mb2.wallet, COUNT(DISTINCT mb2.mint)::int AS mint_count
                                FROM migration_buyers mb2
                                JOIN entity_wallets ew2 ON ew2.wallet = mb2.wallet
                                WHERE ew2.entity_id = :eid
                                GROUP BY mb2.wallet
                            ) wallet_counts ON wallet_counts.wallet = mb.wallet
                            WHERE ew.entity_id = :eid
                            """
                        ),
                        {"eid": entity_id},
                    )
                ).mappings().first()
            except Exception:
                return {
                    "early_buyer_wallet_count": None,
                    "early_buyer_mint_count": None,
                    "repeat_early_buyer_wallet_count": None,
                    "evidence_basis": "unknown_table_or_query",
                }
        return {
            "early_buyer_wallet_count": row["early_buyer_wallet_count"] if row else 0,
            "early_buyer_mint_count": row["early_buyer_mint_count"] if row else 0,
            "repeat_early_buyer_wallet_count": row["repeat_early_buyer_wallet_count"] if row else 0,
            "evidence_basis": "migration_buyers",
        }

    async def refresh_entity(self, entity_id: UUID) -> dict[str, Any]:
        """Recompute from stored observations; never infer missing outcomes."""
        launches = await self._launches_for_entity(entity_id)
        wallets = await self._wallets_for_entity(entity_id)
        early_buy_stats = await self._early_buy_stats(entity_id)
        fingerprint = build_behavioral_fingerprint(
            launches,
            wallets=wallets,
            early_buy_stats=early_buy_stats,
        )
        computed_at = datetime.now(timezone.utc)
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO entity_behavior_fingerprints (
                        entity_id, launch_count, outcomes_known, completed_count,
                        outcomes_unknown, first_launch_at, last_launch_at,
                        median_launch_interval_sec, cadence_bucket, wallet_count,
                        early_buyer_wallet_count, early_buyer_mint_count,
                        repeat_early_buyer_wallet_count, wallet_role_counts,
                        fingerprint, computed_at
                    ) VALUES (
                        :eid, :launch_count, :outcomes_known, :completed_count,
                        :outcomes_unknown, :first_launch_at, :last_launch_at,
                        :median_interval, :cadence, :wallet_count,
                        :early_buyer_wallet_count, :early_buyer_mint_count,
                        :repeat_early_buyer_wallet_count, CAST(:wallet_role_counts AS jsonb),
                        CAST(:fingerprint AS jsonb), :computed_at
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
                        wallet_count = EXCLUDED.wallet_count,
                        early_buyer_wallet_count = EXCLUDED.early_buyer_wallet_count,
                        early_buyer_mint_count = EXCLUDED.early_buyer_mint_count,
                        repeat_early_buyer_wallet_count = EXCLUDED.repeat_early_buyer_wallet_count,
                        wallet_role_counts = EXCLUDED.wallet_role_counts,
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
                    "wallet_count": fingerprint["wallet_count"],
                    "early_buyer_wallet_count": fingerprint["early_buyer_wallet_count"],
                    "early_buyer_mint_count": fingerprint["early_buyer_mint_count"],
                    "repeat_early_buyer_wallet_count": fingerprint["repeat_early_buyer_wallet_count"],
                    "wallet_role_counts": orjson.dumps(fingerprint["wallet_role_counts"]).decode(),
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
