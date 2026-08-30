"""Persistence: subscriptions + event queries from Postgres."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from discord_bot.config import settings

logger = structlog.get_logger(__name__)

# Program / system / known AMM accounts — never rank as "smart money"
LEADERBOARD_DENYLIST: frozenset[str] = frozenset(
    {
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "ComputeBudget111111111111111111111111111111",
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "JUP4Fb2cqiRUcaTHdrLCGBKqKghvh9j8sH4k6b3p5s1",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "SysvarRent111111111111111111111111111111111",
        "SysvarC1ock11111111111111111111111111111111",
    }
)


def _is_rankable_wallet(wallet: str | None) -> bool:
    if not wallet or len(wallet) < 32:
        return False
    return wallet not in LEADERBOARD_DENYLIST


class Store:
    def __init__(self) -> None:
        self._engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=5
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_schema(self) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS discord_subscriptions (
                        user_id     BIGINT PRIMARY KEY,
                        username    TEXT,
                        subscribed  BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            await session.commit()

    async def subscribe(self, user_id: int, username: str | None = None) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO discord_subscriptions (user_id, username, subscribed)
                    VALUES (:uid, :uname, TRUE)
                    ON CONFLICT (user_id) DO UPDATE SET
                        subscribed = TRUE,
                        username = COALESCE(EXCLUDED.username, discord_subscriptions.username),
                        updated_at = now()
                    """
                ),
                {"uid": user_id, "uname": username},
            )
            await session.commit()

    async def unsubscribe(self, user_id: int) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO discord_subscriptions (user_id, subscribed)
                    VALUES (:uid, FALSE)
                    ON CONFLICT (user_id) DO UPDATE SET
                        subscribed = FALSE,
                        updated_at = now()
                    """
                ),
                {"uid": user_id},
            )
            await session.commit()

    async def is_subscribed(self, user_id: int) -> bool:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT subscribed FROM discord_subscriptions WHERE user_id = :uid"
                    ),
                    {"uid": user_id},
                )
            ).first()
            return bool(row and row[0])

    async def list_subscribers(self) -> list[int]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT user_id FROM discord_subscriptions WHERE subscribed = TRUE"
                    )
                )
            ).fetchall()
            return [int(r[0]) for r in rows]

    async def record_discord_delivery(self, rec: dict[str, Any]) -> None:
        """Persist policy vs delivery. Fail-soft at the caller."""
        import json

        ddl = """
        CREATE TABLE IF NOT EXISTS discord_deliveries (
            id BIGSERIAL PRIMARY KEY,
            mint TEXT,
            at TIMESTAMPTZ NOT NULL,
            policy TEXT,
            category TEXT,
            delivery TEXT,
            error TEXT,
            row JSONB NOT NULL
        )
        """
        sql = """
        INSERT INTO discord_deliveries (mint, at, policy, category, delivery, error, row)
        VALUES (:mint, :at, :policy, :category, :delivery, :error, CAST(:row AS jsonb))
        """
        async with self._sessions() as session:
            await session.execute(text(ddl))
            await session.execute(
                text(sql),
                {
                    "mint": rec.get("mint"),
                    "at": rec.get("at"),
                    "policy": rec.get("policy"),
                    "category": rec.get("category"),
                    "delivery": rec.get("delivery"),
                    "error": rec.get("error"),
                    "row": json.dumps(rec, default=str),
                },
            )
            await session.commit()

    async def recent_events(
        self, event_type: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    SELECT event_id, event_type, occurred_at, signature, payload, producer
                    FROM events
                    WHERE event_type = :etype
                    ORDER BY occurred_at DESC
                    LIMIT :lim
                    """
                ),
                {"etype": event_type, "lim": limit},
            )
            out = []
            for row in result.mappings():
                out.append(
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "occurred_at": row["occurred_at"],
                        "signature": row["signature"],
                        "payload": row["payload"] or {},
                        "producer": row["producer"],
                    }
                )
            return out

    async def market_by_mint(self, mint: str) -> dict[str, Any]:
        """Aggregate launch + migration + volume events for a mint."""
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    SELECT event_type, occurred_at, payload, signature
                    FROM events
                    WHERE payload->>'mint' = :mint
                    ORDER BY occurred_at ASC
                    """
                ),
                {"mint": mint},
            )
            events = [dict(r) for r in result.mappings()]
        launch = next((e for e in events if e["event_type"] == "token.launch"), None)
        migrated = next((e for e in events if e["event_type"] == "token.migrated"), None)
        volume = next(
            (e for e in reversed(events) if e["event_type"] == "volume.threshold"), None
        )
        alert = next(
            (e for e in reversed(events) if e["event_type"] == "alert.candidate"), None
        )
        return {
            "mint": mint,
            "launch": launch,
            "migrated": migrated,
            "volume": volume,
            "alert": alert,
            "event_count": len(events),
        }

    async def deployer_stats(self, address: str) -> dict[str, Any]:
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS launches,
                           MIN(occurred_at) AS first_seen,
                           MAX(occurred_at) AS last_seen
                    FROM events
                    WHERE event_type = 'token.launch'
                      AND payload->>'deployer' = :addr
                    """
                ),
                {"addr": address},
            )
            row = result.mappings().first() or {}
            mints = await session.execute(
                text(
                    """
                    SELECT payload->>'mint' AS mint, payload->>'name' AS name, occurred_at
                    FROM events
                    WHERE event_type = 'token.launch'
                      AND payload->>'deployer' = :addr
                    ORDER BY occurred_at DESC
                    LIMIT 10
                    """
                ),
                {"addr": address},
            )
            return {
                "address": address,
                "launches": int(row.get("launches") or 0),
                "first_seen": row.get("first_seen"),
                "last_seen": row.get("last_seen"),
                "recent": [dict(m) for m in mints.mappings()],
            }


    async def sync_early_buy_counts(self) -> int:
        """Upsert early_buy_count / tokens_purchased from migration_buyers into wallet_performance.

        Safe when performance rows are missing; does not wipe hit_rate / PnL fields.
        Returns number of wallets touched.
        """
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO wallet_performance (
                            wallet, early_buy_count, tokens_purchased, updated_at
                        )
                        SELECT wallet,
                               COUNT(*)::int AS early_buy_count,
                               COUNT(DISTINCT mint)::int AS tokens_purchased,
                               now()
                        FROM migration_buyers
                        GROUP BY wallet
                        ON CONFLICT (wallet) DO UPDATE SET
                            early_buy_count = EXCLUDED.early_buy_count,
                            tokens_purchased = GREATEST(
                                wallet_performance.tokens_purchased,
                                EXCLUDED.tokens_purchased
                            ),
                            updated_at = now()
                        """
                    )
                )
                await session.commit()
                return int(result.rowcount or 0)
            except Exception as exc:
                logger.warning("store.sync_early_buy_counts_failed", error=str(exc))
                return 0

    async def _known_pool_wallets(self) -> set[str]:
        """Pool addresses from migration_tracks — exclude from smart leaderboards."""
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT DISTINCT pool FROM migration_tracks
                        WHERE pool IS NOT NULL AND length(pool) >= 32
                        """
                    )
                )
                return {str(r[0]) for r in result.fetchall() if r[0]}
            except Exception:
                return set()

    async def top_smart_wallets(self, *, limit: int = 15) -> list[dict[str, Any]]:
        """Rank wallets by Smart Score (early buys, hit rate, returns).

        1) Sync early counts from migration_buyers
        2) Prefer wallet_performance rows
        3) Fallback: aggregate migration_buyers only
        4) Drop program / AMM / known pool addresses
        """
        from discord_bot.ranker import rank_rows

        await self.sync_early_buy_counts()
        pools = await self._known_pool_wallets()
        blocked = LEADERBOARD_DENYLIST | pools

        async with self._sessions() as session:
            rows: list[dict[str, Any]] = []
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT wallet, total_trades, total_buys, total_sells,
                               tokens_purchased, early_buy_count, qualifying_trades,
                               wins, losses, loss_rate, hit_rate,
                               avg_return_pct, median_return_pct, max_return_pct,
                               avg_holding_seconds, realized_pnl_usd, realized_pnl_sol,
                               milestones_hit, updated_at
                        FROM wallet_performance
                        WHERE (early_buy_count > 0 OR total_buys > 0)
                          AND wallet <> ALL(:blocked)
                        ORDER BY early_buy_count DESC NULLS LAST,
                                 hit_rate DESC NULLS LAST,
                                 avg_return_pct DESC NULLS LAST
                        LIMIT :lim
                        """
                    ),
                    {
                        "lim": max(limit * 5, 50),
                        "blocked": list(blocked) or [""],
                    },
                )
                rows = [dict(r) for r in result.mappings()]
            except Exception as exc:
                logger.warning("store.top_smart_wallets_perf_failed", error=str(exc))
                rows = []

            if not rows:
                try:
                    result = await session.execute(
                        text(
                            """
                            SELECT wallet,
                                   COUNT(*)::int AS early_buy_count,
                                   COUNT(DISTINCT mint)::int AS tokens_purchased,
                                   0 AS total_trades,
                                   0 AS total_buys,
                                   0 AS total_sells,
                                   0 AS qualifying_trades,
                                   0 AS wins,
                                   0 AS losses,
                                   NULL::numeric AS hit_rate,
                                   NULL::numeric AS avg_return_pct,
                                   NULL::numeric AS median_return_pct,
                                   NULL::numeric AS max_return_pct,
                                   0::numeric AS realized_pnl_usd,
                                   0::numeric AS realized_pnl_sol
                            FROM migration_buyers
                            WHERE wallet <> ALL(:blocked)
                            GROUP BY wallet
                            ORDER BY early_buy_count DESC
                            LIMIT :lim
                            """
                        ),
                        {
                            "lim": max(limit * 5, 50),
                            "blocked": list(blocked) or [""],
                        },
                    )
                    rows = [dict(r) for r in result.mappings()]
                except Exception as exc:
                    logger.warning("store.top_smart_wallets_buyers_failed", error=str(exc))
                    return []

        rows = [r for r in rows if _is_rankable_wallet(r.get("wallet")) and r.get("wallet") not in pools]
        ranked = rank_rows(rows)
        return ranked[:limit]

    async def wallet_performance(self, address: str) -> dict[str, Any] | None:
        from discord_bot.ranker import rank_rows

        async with self._sessions() as session:
            try:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM wallet_performance
                            WHERE wallet = :addr
                            """
                        ),
                        {"addr": address},
                    )
                ).mappings().first()
            except Exception:
                row = None

            if row:
                ranked = rank_rows([dict(row)])
                return ranked[0]

            # Fallback: counts from migration_buyers only
            try:
                agg = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet,
                                   COUNT(*)::int AS early_buy_count,
                                   COUNT(DISTINCT mint)::int AS tokens_purchased
                            FROM migration_buyers
                            WHERE wallet = :addr
                            GROUP BY wallet
                            """
                        ),
                        {"addr": address},
                    )
                ).mappings().first()
            except Exception:
                return None
            if not agg:
                return None
            ranked = rank_rows([dict(agg)])
            return ranked[0]

    async def migration_buyers(self, mint: str, *, limit: int = 20) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT rank, wallet, signature, bought_at, slot,
                               token_amount, sol_spent, usd_spent, entry_price_usd
                        FROM migration_buyers
                        WHERE mint = :mint
                        ORDER BY rank ASC
                        LIMIT :lim
                        """
                    ),
                    {"mint": mint, "lim": limit},
                )
            except Exception:
                return []
            return [dict(r) for r in result.mappings()]

    async def early_buyer_patterns(
        self, *, min_mints: int = 2, limit: int = 15
    ) -> list[dict[str, Any]]:
        """Wallets that appear as early buyers on ≥ min_mints migrations.

        Excludes program / AMM / known pool addresses.
        """
        pools = await self._known_pool_wallets()
        blocked = list(LEADERBOARD_DENYLIST | pools) or [""]
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT wallet,
                               COUNT(DISTINCT mint)::int AS migration_count,
                               COUNT(*)::int AS early_appearances,
                               MIN(rank)::int AS best_rank,
                               AVG(rank)::float AS avg_rank,
                               SUM(COALESCE(sol_spent, 0))::float AS total_sol_spent,
                               MAX(bought_at) AS last_seen
                        FROM migration_buyers
                        WHERE wallet <> ALL(:blocked)
                        GROUP BY wallet
                        HAVING COUNT(DISTINCT mint) >= :min_mints
                        ORDER BY migration_count DESC, early_appearances DESC, best_rank ASC
                        LIMIT :lim
                        """
                    ),
                    {"min_mints": min_mints, "lim": max(limit * 2, 20), "blocked": blocked},
                )
            except Exception as exc:
                logger.warning("store.early_buyer_patterns_failed", error=str(exc))
                return []
            rows = [dict(r) for r in result.mappings()]
            return [r for r in rows if _is_rankable_wallet(r.get("wallet"))][:limit]

    async def recent_migrated_mints(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Recent token.migrated events with optional buyer counts."""
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT e.payload->>'mint' AS mint,
                               e.payload->>'pool' AS pool,
                               e.payload->>'creator' AS creator,
                               e.occurred_at,
                               (
                                   SELECT COUNT(*)::int FROM migration_buyers mb
                                   WHERE mb.mint = e.payload->>'mint'
                               ) AS buyer_count
                        FROM events e
                        WHERE e.event_type = 'token.migrated'
                        ORDER BY e.occurred_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            except Exception as exc:
                logger.warning("store.recent_migrated_failed", error=str(exc))
                return []
            return [dict(r) for r in result.mappings()]

    async def entity_for_wallet(self, wallet: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            try:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT e.entity_id, e.entity_type, e.display_label,
                                   e.primary_wallet, e.wallet_count, e.launch_count,
                                   e.early_buy_count, e.confidence
                            FROM entity_wallets ew
                            JOIN entities e ON e.entity_id = ew.entity_id
                            WHERE ew.wallet = :w
                            """
                        ),
                        {"w": wallet},
                    )
                ).mappings().first()
            except Exception:
                return None
            return dict(row) if row else None

    async def entity_wallets(self, entity_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet, role, link_reason, confidence
                            FROM entity_wallets
                            WHERE entity_id = CAST(:eid AS uuid)
                            ORDER BY role, wallet
                            """
                        ),
                        {"eid": entity_id},
                    )
                ).mappings().all()
            except Exception:
                return []
            return [dict(r) for r in rows]

    async def top_entities(self, *, limit: int = 10) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT entity_id, entity_type, display_label, primary_wallet,
                                   wallet_count, launch_count, early_buy_count, confidence
                            FROM entities
                            ORDER BY launch_count DESC, early_buy_count DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
            except Exception:
                return []
            return [dict(r) for r in rows]

    async def log_alert(
        self,
        *,
        mint: str,
        score: float | None,
        confidence: float | None,
        volume_m5_usd: float | None,
        meaningful_buyers: int | None,
        entity_launch_count: int | None,
        score_model: str | None,
        name: str | None,
        symbol: str | None,
        deployer: str | None,
        dm_sent: bool,
        channel_posted: bool,
        payload: dict[str, Any],
    ) -> str | None:
        """Persist a gated alert for later outcome measurement."""
        import json
        try:
            async with self._sessions() as session:
                await session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS alert_log (
                            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                            mint TEXT NOT NULL,
                            alerted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            score DOUBLE PRECISION,
                            confidence DOUBLE PRECISION,
                            volume_m5_usd DOUBLE PRECISION,
                            meaningful_buyers INT,
                            entity_launch_count INT,
                            score_model TEXT,
                            name TEXT,
                            symbol TEXT,
                            deployer TEXT,
                            dm_sent BOOLEAN NOT NULL DEFAULT TRUE,
                            channel_posted BOOLEAN NOT NULL DEFAULT FALSE,
                            payload JSONB,
                            UNIQUE (mint, alerted_at)
                        )
                        """
                    )
                )
                row = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO alert_log (
                                mint, score, confidence, volume_m5_usd,
                                meaningful_buyers, entity_launch_count, score_model,
                                name, symbol, deployer, dm_sent, channel_posted, payload
                            ) VALUES (
                                :mint, :score, :conf, :vol,
                                :mb, :elc, :model,
                                :name, :symbol, :deployer, :dm, :ch, CAST(:payload AS jsonb)
                            )
                            RETURNING id::text
                            """
                        ),
                        {
                            "mint": mint,
                            "score": score,
                            "conf": confidence,
                            "vol": volume_m5_usd,
                            "mb": meaningful_buyers,
                            "elc": entity_launch_count,
                            "model": score_model,
                            "name": name,
                            "symbol": symbol,
                            "deployer": deployer,
                            "dm": dm_sent,
                            "ch": channel_posted,
                            "payload": json.dumps(payload, default=str),
                        },
                    )
                ).first()
                await session.commit()
                return row[0] if row else None
        except Exception as exc:
            logger.warning("store.log_alert_failed", error=str(exc), mint=mint)
            return None


    async def recent_alert_mints(self, *, hours: int = 48) -> set[str]:
        """Mints already alerted recently (dedupe source of truth)."""
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT DISTINCT mint FROM alert_log
                            WHERE alerted_at > now() - make_interval(hours => :h)
                            """
                        ),
                        {"h": hours},
                    )
                ).all()
                return {r[0] for r in rows if r[0]}
            except Exception:
                try:
                    rows = (
                        await session.execute(
                            text(
                                """
                                SELECT DISTINCT payload->>'mint' FROM events
                                WHERE event_type = 'alert.candidate'
                                  AND occurred_at > now() - make_interval(hours => :h)
                                """
                            ),
                            {"h": hours},
                        )
                    ).all()
                    return {r[0] for r in rows if r[0]}
                except Exception:
                    return set()

    async def alert_precision_summary(self, *, limit: int = 50) -> dict[str, Any]:
        """Counts of labeled outcomes + runner rate from alert_log / alert_outcomes."""
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT a.mint, a.score, a.alerted_at,
                                   COALESCE(o.label, 'unknown') AS label,
                                   o.volume_multiple, o.peak_volume_m5_usd
                            FROM alert_log a
                            LEFT JOIN alert_outcomes o ON o.alert_id = a.id
                            ORDER BY a.alerted_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
            except Exception:
                try:
                    rows = (
                        await session.execute(
                            text(
                                """
                                SELECT mint, score, alerted_at, 'unknown' AS label,
                                       NULL::float AS volume_multiple,
                                       NULL::float AS peak_volume_m5_usd
                                FROM alert_log
                                ORDER BY alerted_at DESC
                                LIMIT :lim
                                """
                            ),
                            {"lim": limit},
                        )
                    ).mappings().all()
                except Exception as exc:
                    return {
                        "available": False,
                        "message": str(exc)[:200],
                        "counts": {},
                        "items": [],
                        "total": 0,
                        "runner_rate": None,
                    }

            items = [dict(r) for r in rows]
            counts: dict[str, int] = {}
            for it in items:
                lab = str(it.get("label") or "unknown")
                counts[lab] = counts.get(lab, 0) + 1
            total = len(items)
            runners = counts.get("runner", 0)
            return {
                "available": True,
                "counts": counts,
                "total": total,
                "runner_rate": (runners / total) if total else None,
                "items": items,
            }

    async def recent_alert_log(self, *, limit: int = 15) -> list[dict[str, Any]]:
        """Latest gated alerts we actually DM'd / logged."""
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT a.mint, a.score, a.confidence, a.volume_m5_usd,
                                   a.meaningful_buyers, a.name, a.symbol, a.alerted_at,
                                   a.dm_sent, COALESCE(o.label, 'unknown') AS label
                            FROM alert_log a
                            LEFT JOIN alert_outcomes o ON o.alert_id = a.id
                            ORDER BY a.alerted_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception:
                try:
                    rows = (
                        await session.execute(
                            text(
                                """
                                SELECT mint, score, confidence, volume_m5_usd,
                                       meaningful_buyers, name, symbol, alerted_at,
                                       dm_sent, 'unknown' AS label
                                FROM alert_log
                                ORDER BY alerted_at DESC
                                LIMIT :lim
                                """
                            ),
                            {"lim": limit},
                        )
                    ).mappings().all()
                    return [dict(r) for r in rows]
                except Exception:
                    return []

    async def top_success_wallets(self, *, limit: int = 15) -> list[dict[str, Any]]:
        """Early buyers ranked by measured success on labeled runner/mega tokens."""
        async with self._sessions() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet, early_entries, early_on_mega, early_on_runner,
                                   early_on_mid, early_on_fade, success_rate, sample_size,
                                   last_success_at, updated_at
                            FROM wallet_early_success
                            WHERE sample_size >= 1
                            ORDER BY success_rate DESC NULLS LAST,
                                     early_on_mega DESC,
                                     early_on_runner DESC,
                                     sample_size DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception as exc:
                logger.warning("store.top_success_wallets_failed", error=str(exc))
                return []

    async def _ensure_watchlist(self, session) -> None:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS stinky_watchlist (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    kind TEXT NOT NULL CHECK (kind IN ('wallet', 'mint')),
                    address TEXT NOT NULL,
                    note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (kind, address)
                )
                """
            )
        )

    async def watchlist_add(self, *, kind: str, address: str, note: str | None = None) -> None:
        async with self._sessions() as session:
            await self._ensure_watchlist(session)
            await session.execute(
                text(
                    """
                    INSERT INTO stinky_watchlist (kind, address, note)
                    VALUES (:k, :a, :n)
                    ON CONFLICT (kind, address) DO UPDATE
                    SET note = COALESCE(EXCLUDED.note, stinky_watchlist.note)
                    """
                ),
                {"k": kind, "a": address.strip(), "n": note},
            )
            await session.commit()

    async def watchlist_remove(self, *, kind: str, address: str) -> bool:
        async with self._sessions() as session:
            await self._ensure_watchlist(session)
            r = await session.execute(
                text("DELETE FROM stinky_watchlist WHERE kind = :k AND address = :a"),
                {"k": kind, "a": address.strip()},
            )
            await session.commit()
            return (r.rowcount or 0) > 0

    async def watchlist_list(self, *, limit: int = 25) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            try:
                await self._ensure_watchlist(session)
                await session.commit()
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT kind, address, note, created_at
                            FROM stinky_watchlist
                            ORDER BY created_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                ).mappings().all()
                return [dict(r) for r in rows]
            except Exception as exc:
                logger.warning("store.watchlist_list_failed", error=str(exc))
                return []
