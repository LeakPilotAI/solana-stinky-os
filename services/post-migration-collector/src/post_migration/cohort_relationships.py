"""Temporal-safe relationship evidence for recurring early-buyer cohorts.

Joins #140 recurring pairs to existing factual wallet relationship/funding
evidence. Descriptive only: no ownership, coordination, intent, quality, risk,
prediction, or trade authority is inferred.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from post_migration.config import settings

class CohortRelationshipStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
        self._engine = create_async_engine(url, pool_pre_ping=True, pool_size=3)
        self._sessions = async_sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)

    async def close(self) -> None:
        await self._engine.dispose()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    async def _has_table(self, session: AsyncSession, name: str) -> bool:
        row = (await session.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{name}"})).first()
        return bool(row and row[0])

    async def list_pair_relationship_evidence(self, *, wallet_a: str, wallet_b: str, as_of: datetime, limit: int = 100) -> dict[str, Any]:
        """Return only evidence observable at/before mandatory point-in-time cutoff."""
        first, second = str(wallet_a or "").strip(), str(wallet_b or "").strip()
        cutoff = self._utc(as_of)
        if not first or not second or first == second:
            return {"wallet_a": first, "wallet_b": second, "as_of": cutoff, "relationship_table_available": False, "funding_table_available": False, "relationships": [], "funding_observations": []}
        if first > second:
            first, second = second, first
        bounded_limit = max(1, min(int(limit), 500))
        async with self._sessions() as session:
            has_relationships = await self._has_table(session, "wallet_relationships")
            has_funding = await self._has_table(session, "wallet_funding_observations")
            relationships: list[dict[str, Any]] = []
            if has_relationships:
                rows = (await session.execute(text("""
                    SELECT wallet_a, wallet_b, relationship_kind, observation_count,
                           first_seen_at, last_seen_at, confidence, evidence
                    FROM wallet_relationships
                    WHERE wallet_a=:wallet_a AND wallet_b=:wallet_b AND first_seen_at<=:as_of
                    ORDER BY last_seen_at DESC, relationship_kind ASC LIMIT :limit
                """), {"wallet_a": first, "wallet_b": second, "as_of": cutoff, "limit": bounded_limit})).mappings().all()
                for row in rows:
                    item = dict(row)
                    if item.get("last_seen_at") and item["last_seen_at"] > cutoff:
                        # This table is a mutable aggregate. If it spans beyond the
                        # replay boundary, its count/evidence/confidence may contain
                        # future information. Fail closed instead of leaking it.
                        item["observation_count"] = None
                        item["last_seen_at"] = None
                        item["confidence"] = None
                        item["evidence"] = {}
                        item["point_in_time_aggregate_unknown"] = True
                    else:
                        item["point_in_time_aggregate_unknown"] = False
                    relationships.append(item)
            funding: list[dict[str, Any]] = []
            if has_funding:
                rows = (await session.execute(text("""
                    SELECT signature, source_wallet, destination_wallet, observed_at,
                           amount_lamports, evidence
                    FROM wallet_funding_observations
                    WHERE observed_at<=:as_of AND (
                      (source_wallet=:wallet_a AND destination_wallet=:wallet_b) OR
                      (source_wallet=:wallet_b AND destination_wallet=:wallet_a))
                    ORDER BY observed_at DESC, signature ASC LIMIT :limit
                """), {"wallet_a": first, "wallet_b": second, "as_of": cutoff, "limit": bounded_limit})).mappings().all()
                funding = [dict(row) for row in rows]
        return {"wallet_a": first, "wallet_b": second, "as_of": cutoff, "relationship_table_available": has_relationships, "funding_table_available": has_funding, "relationships": relationships, "funding_observations": funding}

    async def summarize_pair_relationship_evidence(self, *, wallet_a: str, wallet_b: str, as_of: datetime) -> dict[str, Any]:
        evidence = await self.list_pair_relationship_evidence(wallet_a=wallet_a, wallet_b=wallet_b, as_of=as_of, limit=500)
        funding = evidence["funding_observations"]
        kinds = sorted({row["relationship_kind"] for row in evidence["relationships"]})
        return {"wallet_a": evidence["wallet_a"], "wallet_b": evidence["wallet_b"], "as_of": evidence["as_of"], "relationship_table_available": evidence["relationship_table_available"], "funding_table_available": evidence["funding_table_available"], "relationship_kinds": kinds, "direct_funding_observations": len(funding), "funding_sources": sorted({r["source_wallet"] for r in funding}), "funding_destinations": sorted({r["destination_wallet"] for r in funding}), "has_observable_relationship_evidence": bool(kinds or funding)}
