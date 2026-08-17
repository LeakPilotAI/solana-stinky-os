"""Postgres persistence for entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import orjson
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings

logger = structlog.get_logger(__name__)


class EntityStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._engine = create_async_engine(
            database_url or settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_schema(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "001_entity_schema.sql"
        )
        async with self._sessions() as session:
            exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'entities'
                        """
                    )
                )
            ).first()
            if exists:
                logger.info("entity_store.schema_present")
                return

        if not path.exists():
            logger.warning("entity_store.migration_missing", path=str(path))
            return

        sql = path.read_text(encoding="utf-8")
        cleaned = "\n".join(
            line for line in sql.splitlines() if not line.strip().startswith("--")
        )
        async with self._sessions() as session:
            for stmt in cleaned.split(";"):
                s = stmt.strip()
                if s:
                    await session.execute(text(s))
            await session.commit()
        logger.info("entity_store.schema_ensured")

    async def get_entity_for_wallet(self, wallet: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT e.entity_id, e.entity_type, e.display_label,
                               e.primary_wallet, e.wallet_count, e.launch_count,
                               e.early_buy_count, e.confidence, e.meta,
                               ew.role, ew.link_reason, ew.confidence AS link_confidence
                        FROM entity_wallets ew
                        JOIN entities e ON e.entity_id = ew.entity_id
                        WHERE ew.wallet = :wallet
                        """
                    ),
                    {"wallet": wallet},
                )
            ).mappings().first()
            return dict(row) if row else None

    async def list_wallets(self, entity_id: UUID) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, role, link_reason, confidence,
                               first_seen_at, last_seen_at
                        FROM entity_wallets
                        WHERE entity_id = :eid
                        ORDER BY role, wallet
                        """
                    ),
                    {"eid": entity_id},
                )
            ).mappings().all()
            return [dict(r) for r in rows]

    async def create_entity(
        self,
        *,
        primary_wallet: str,
        entity_type: str = "operator",
        display_label: str | None = None,
        confidence: float = 0.5,
        meta: dict[str, Any] | None = None,
    ) -> UUID:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO entities (
                            entity_type, display_label, primary_wallet,
                            wallet_count, confidence, meta
                        ) VALUES (
                            :etype, :label, :pw, 0, :conf, CAST(:meta AS jsonb)
                        )
                        RETURNING entity_id
                        """
                    ),
                    {
                        "etype": entity_type,
                        "label": display_label or primary_wallet[:8],
                        "pw": primary_wallet,
                        "conf": confidence,
                        "meta": orjson.dumps(meta or {}).decode(),
                    },
                )
            ).first()
            assert row is not None
            entity_id = row[0]
            await session.execute(
                text(
                    """
                    INSERT INTO entity_wallets (
                        entity_id, wallet, role, link_reason, confidence
                    ) VALUES (
                        :eid, :wallet, 'primary', 'entity_created', :conf
                    )
                    ON CONFLICT (wallet) DO NOTHING
                    """
                ),
                {"eid": entity_id, "wallet": primary_wallet, "conf": confidence},
            )
            await session.execute(
                text(
                    """
                    UPDATE entities SET wallet_count = (
                        SELECT COUNT(*) FROM entity_wallets WHERE entity_id = :eid
                    ), updated_at = now()
                    WHERE entity_id = :eid
                    """
                ),
                {"eid": entity_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO entity_link_events (
                        event_kind, entity_id, wallet, reason, confidence, evidence
                    ) VALUES (
                        'created', :eid, :wallet, 'entity_created', :conf, '{}'::jsonb
                    )
                    """
                ),
                {"eid": entity_id, "wallet": primary_wallet, "conf": confidence},
            )
            await session.commit()
            return entity_id

    async def link_wallet(
        self,
        *,
        entity_id: UUID,
        wallet: str,
        role: str,
        reason: str,
        confidence: float,
        evidence: dict[str, Any] | None = None,
        seen_at: datetime | None = None,
    ) -> bool:
        """Link wallet to entity. Returns False if wallet already owned by another entity."""
        async with self._sessions() as session:
            existing = (
                await session.execute(
                    text("SELECT entity_id FROM entity_wallets WHERE wallet = :w"),
                    {"w": wallet},
                )
            ).first()
            if existing:
                if existing[0] == entity_id:
                    return True
                return False

            await session.execute(
                text(
                    """
                    INSERT INTO entity_wallets (
                        entity_id, wallet, role, link_reason, confidence,
                        first_seen_at, last_seen_at, evidence
                    ) VALUES (
                        :eid, :wallet, :role, :reason, :conf,
                        :seen, :seen, CAST(:ev AS jsonb)
                    )
                    """
                ),
                {
                    "eid": entity_id,
                    "wallet": wallet,
                    "role": role,
                    "reason": reason,
                    "conf": confidence,
                    "seen": seen_at,
                    "ev": orjson.dumps(evidence or {}).decode(),
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE entities SET
                        wallet_count = (SELECT COUNT(*) FROM entity_wallets WHERE entity_id = :eid),
                        updated_at = now()
                    WHERE entity_id = :eid
                    """
                ),
                {"eid": entity_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO entity_link_events (
                        event_kind, entity_id, wallet, reason, confidence, evidence
                    ) VALUES (
                        'linked', :eid, :wallet, :reason, :conf, CAST(:ev AS jsonb)
                    )
                    """
                ),
                {
                    "eid": entity_id,
                    "wallet": wallet,
                    "reason": reason,
                    "conf": confidence,
                    "ev": orjson.dumps(evidence or {}).decode(),
                },
            )
            await session.commit()
            return True

    async def bump_launch_count(self, entity_id: UUID) -> None:
        async with self._sessions() as session:
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

    async def bump_early_buy_count(self, entity_id: UUID) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE entities
                    SET early_buy_count = early_buy_count + 1, updated_at = now()
                    WHERE entity_id = :eid
                    """
                ),
                {"eid": entity_id},
            )
            await session.commit()

    async def ensure_wallet_entity(
        self,
        wallet: str,
        *,
        entity_type: str = "operator",
        role: str = "primary",
        reason: str = "observed",
        confidence: float = 0.5,
    ) -> UUID:
        existing = await self.get_entity_for_wallet(wallet)
        if existing:
            return existing["entity_id"]
        return await self.create_entity(
            primary_wallet=wallet,
            entity_type=entity_type,
            confidence=confidence,
        )

    async def top_entities(self, *, limit: int = 15) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT entity_id, entity_type, display_label, primary_wallet,
                               wallet_count, launch_count, early_buy_count, confidence
                        FROM entities
                        ORDER BY launch_count DESC, early_buy_count DESC, wallet_count DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            return [dict(r) for r in rows]

    async def deployers_from_events(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT payload->>'deployer' AS deployer,
                                   COUNT(*)::int AS launches,
                                   MIN(occurred_at) AS first_seen,
                                   MAX(occurred_at) AS last_seen
                            FROM events
                            WHERE event_type = 'token.launch'
                              AND payload->>'deployer' IS NOT NULL
                            GROUP BY payload->>'deployer'
                            """
                        )
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception:
                return []

    async def early_buyer_pairs(self, min_overlap: int) -> list[dict[str, Any]]:
        """Wallets that co-appear as early buyers on ≥ min_overlap mints."""
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT a.wallet AS wallet_a, b.wallet AS wallet_b,
                                   COUNT(*)::int AS shared_mints
                            FROM migration_buyers a
                            JOIN migration_buyers b
                              ON a.mint = b.mint AND a.wallet < b.wallet
                            GROUP BY a.wallet, b.wallet
                            HAVING COUNT(*) >= :min_overlap
                            ORDER BY shared_mints DESC
                            LIMIT 500
                            """
                        ),
                        {"min_overlap": min_overlap},
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception:
                return []

    async def merge_entities(
        self,
        *,
        survivor_id: Any,
        absorbed_id: Any,
        reason: str,
        confidence: float,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        """Move all wallets from absorbed → survivor. Never deletes event history.

        Safety: both entities must exist; absorbed != survivor.
        """
        if str(survivor_id) == str(absorbed_id):
            return False
        async with self._sessions() as session:
            sa = (
                await session.execute(
                    text("SELECT entity_id, primary_wallet, launch_count, early_buy_count, confidence FROM entities WHERE entity_id = :id"),
                    {"id": survivor_id},
                )
            ).mappings().first()
            ab = (
                await session.execute(
                    text("SELECT entity_id, primary_wallet, launch_count, early_buy_count, confidence FROM entities WHERE entity_id = :id"),
                    {"id": absorbed_id},
                )
            ).mappings().first()
            if not sa or not ab:
                return False

            # Reassign wallets (UNIQUE wallet) — clear absorbed first via update
            await session.execute(
                text(
                    """
                    UPDATE entity_wallets
                    SET entity_id = :surv,
                        role = CASE WHEN role = 'primary' THEN 'member' ELSE role END,
                        link_reason = :reason,
                        confidence = GREATEST(confidence, :conf),
                        evidence = COALESCE(evidence, '{}'::jsonb) || CAST(:ev AS jsonb),
                        last_seen_at = now()
                    WHERE entity_id = :abs
                    """
                ),
                {
                    "surv": survivor_id,
                    "abs": absorbed_id,
                    "reason": reason,
                    "conf": confidence,
                    "ev": orjson.dumps(evidence or {}).decode(),
                },
            )

            # Aggregate counts onto survivor
            await session.execute(
                text(
                    """
                    UPDATE entities SET
                        launch_count = GREATEST(launch_count, :lc),
                        early_buy_count = early_buy_count + :eb,
                        confidence = GREATEST(confidence, :conf),
                        wallet_count = (
                            SELECT COUNT(*) FROM entity_wallets WHERE entity_id = :surv
                        ),
                        meta = meta || CAST(:meta AS jsonb),
                        updated_at = now()
                    WHERE entity_id = :surv
                    """
                ),
                {
                    "surv": survivor_id,
                    "lc": int(ab.get("launch_count") or 0),
                    "eb": int(ab.get("early_buy_count") or 0),
                    "conf": confidence,
                    "meta": orjson.dumps(
                        {
                            "merged_from": str(absorbed_id),
                            "merged_primary": ab.get("primary_wallet"),
                            "merge_reason": reason,
                        }
                    ).decode(),
                },
            )

            await session.execute(
                text(
                    """
                    INSERT INTO entity_link_events (
                        event_kind, entity_id, wallet, other_entity_id,
                        reason, confidence, evidence
                    ) VALUES (
                        'merged', :surv, :wallet, :abs,
                        :reason, :conf, CAST(:ev AS jsonb)
                    )
                    """
                ),
                {
                    "surv": survivor_id,
                    "abs": absorbed_id,
                    "wallet": ab.get("primary_wallet"),
                    "reason": reason,
                    "conf": confidence,
                    "ev": orjson.dumps(evidence or {}).decode(),
                },
            )

            # Soft-retire absorbed entity (keep row for audit; zero wallets)
            await session.execute(
                text(
                    """
                    UPDATE entities SET
                        wallet_count = 0,
                        display_label = COALESCE(display_label, '') || ' [merged]',
                        meta = meta || CAST(:meta AS jsonb),
                        updated_at = now()
                    WHERE entity_id = :abs
                    """
                ),
                {
                    "abs": absorbed_id,
                    "meta": orjson.dumps(
                        {
                            "merged_into": str(survivor_id),
                            "status": "merged",
                        }
                    ).decode(),
                },
            )
            await session.commit()
            return True

    async def multi_wallet_entities(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT e.entity_id::text, e.entity_type, e.display_label,
                                   e.primary_wallet, e.wallet_count, e.launch_count,
                                   e.early_buy_count, e.confidence, e.updated_at
                            FROM entities e
                            WHERE e.wallet_count > 1
                              AND COALESCE(e.meta->>'status', '') <> 'merged'
                            ORDER BY e.wallet_count DESC, e.launch_count DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception:
                return []

    async def merge_candidates(
        self, *, min_shared: int = 8, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Pairs of existing entities that share strong co-buy evidence (not yet merged)."""
        pairs = await self.early_buyer_pairs(min_shared)
        out: list[dict[str, Any]] = []
        for p in pairs:
            if len(out) >= limit:
                break
            a, b = p["wallet_a"], p["wallet_b"]
            shared = int(p["shared_mints"])
            ea = await self.get_entity_for_wallet(a)
            eb = await self.get_entity_for_wallet(b)
            if not ea or not eb:
                continue
            if ea["entity_id"] == eb["entity_id"]:
                continue
            if (ea.get("meta") or {}).get("status") == "merged":
                continue
            if (eb.get("meta") or {}).get("status") == "merged":
                continue
            out.append(
                {
                    "wallet_a": a,
                    "wallet_b": b,
                    "shared_mints": shared,
                    "entity_a": str(ea["entity_id"]),
                    "entity_b": str(eb["entity_id"]),
                    "launches_a": ea.get("launch_count"),
                    "launches_b": eb.get("launch_count"),
                    "wallets_a": ea.get("wallet_count"),
                    "wallets_b": eb.get("wallet_count"),
                }
            )
        return out
