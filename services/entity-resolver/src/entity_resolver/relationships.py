"""Persistent, descriptive wallet-to-wallet relationship evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings


class WalletRelationshipStore:
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

        path = Path(__file__).resolve().parents[2] / "migrations" / "005_wallet_relationships.sql"
        sql = path.read_text(encoding="utf-8")
        async with self._sessions() as session:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await session.execute(text(statement))
            await session.commit()

    async def record_relationship(
        self,
        *,
        wallet_a: str,
        wallet_b: str,
        relationship_kind: str,
        observation_count: int = 1,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        confidence: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        if wallet_a == wallet_b:
            return
        a, b = sorted((wallet_a, wallet_b))
        first_seen_at = first_seen_at or datetime.now(timezone.utc)
        last_seen_at = last_seen_at or first_seen_at
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO wallet_relationships (
                        wallet_a, wallet_b, relationship_kind, observation_count,
                        first_seen_at, last_seen_at, confidence, evidence
                    ) VALUES (
                        :a, :b, :kind, :count, :first_seen, :last_seen,
                        :confidence, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (wallet_a, wallet_b, relationship_kind)
                    DO UPDATE SET
                        observation_count = wallet_relationships.observation_count + EXCLUDED.observation_count,
                        first_seen_at = LEAST(wallet_relationships.first_seen_at, EXCLUDED.first_seen_at),
                        last_seen_at = GREATEST(wallet_relationships.last_seen_at, EXCLUDED.last_seen_at),
                        confidence = GREATEST(COALESCE(wallet_relationships.confidence, 0), COALESCE(EXCLUDED.confidence, 0)),
                        evidence = wallet_relationships.evidence || EXCLUDED.evidence,
                        updated_at = now()
                    """
                ),
                {
                    "a": a,
                    "b": b,
                    "kind": relationship_kind,
                    "count": max(1, observation_count),
                    "first_seen": first_seen_at,
                    "last_seen": last_seen_at,
                    "confidence": confidence,
                    "evidence": orjson.dumps(evidence or {}).decode(),
                },
            )
            await session.commit()

    async def record_deployer_buyer_relationships(self, limit: int = 500) -> int:
        """Persist factual deployer↔buyer associations observed on the same launch mint."""
        limit = max(1, min(limit, 500))
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT el.deployer_wallet,
                                   mb.wallet AS buyer_wallet,
                                   COUNT(DISTINCT el.mint)::int AS observed_mints,
                                   MIN(el.observed_at) AS first_seen_at,
                                   MAX(el.observed_at) AS last_seen_at
                            FROM entity_launches el
                            JOIN migration_buyers mb ON mb.mint = el.mint
                            WHERE el.mint IS NOT NULL
                              AND mb.wallet IS NOT NULL
                              AND el.deployer_wallet <> mb.wallet
                            GROUP BY el.deployer_wallet, mb.wallet
                            ORDER BY observed_mints DESC, last_seen_at DESC
                            LIMIT :limit
                            """
                        ),
                        {"limit": limit},
                    )
                ).mappings().all()
            except Exception:
                return 0

        for row in rows:
            await self.record_relationship(
                wallet_a=row["deployer_wallet"],
                wallet_b=row["buyer_wallet"],
                relationship_kind="deployer_buyer_association",
                observation_count=int(row["observed_mints"] or 1),
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                confidence=1.0,
                evidence={
                    "observed_mints": int(row["observed_mints"] or 0),
                    "evidence_basis": "entity_launches+migration_buyers",
                    "confidence_basis": "direct_observed_role_association",
                },
            )
        return len(rows)

    async def list_relationships(self, wallet: str, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet_a, wallet_b, relationship_kind,
                               observation_count, first_seen_at, last_seen_at,
                               confidence, evidence
                        FROM wallet_relationships
                        WHERE wallet_a = :wallet OR wallet_b = :wallet
                        ORDER BY observation_count DESC, last_seen_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"wallet": wallet, "limit": limit},
                )
            ).mappings().all()
            return [dict(row) for row in rows]
