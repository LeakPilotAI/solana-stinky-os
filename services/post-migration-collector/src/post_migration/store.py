"""PostgreSQL persistence for post-migration intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from post_migration.config import settings
from post_migration.models import (
    MarketSnapshot,
    ObservedTrade,
    TrackStatus,
    WalletPerformance,
)
from post_migration.performance import update_position_from_trade

logger = structlog.get_logger(__name__)


class Store:
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

    async def health(self) -> bool:
        try:
            async with self._sessions() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def ensure_schema(self, sql_path: str | None = None) -> None:
        """Apply migration SQL if tables missing (idempotent CREATE IF NOT EXISTS)."""
        from pathlib import Path

        path = (
            Path(sql_path)
            if sql_path
            else Path(__file__).resolve().parents[2]
            / "migrations"
            / "001_post_migration_schema.sql"
        )
        if not path.exists():
            logger.warning("store.migration_missing", path=str(path))
            return

        # Fast path: already migrated
        async with self._sessions() as session:
            exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'migration_tracks'
                        """
                    )
                )
            ).first()
            if exists:
                logger.info("store.schema_present")
                return

        sql = path.read_text(encoding="utf-8")
        # Strip full-line comments before splitting so ';' inside comments is ignored
        cleaned_lines: list[str] = []
        for line in sql.splitlines():
            if line.strip().startswith("--"):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)

        async with self._sessions() as session:
            for stmt in cleaned.split(";"):
                s = stmt.strip()
                if not s:
                    continue
                await session.execute(text(s))
            await session.commit()
        logger.info("store.schema_ensured", path=str(path))

    async def start_track(
        self,
        *,
        mint: str,
        pool: str | None,
        creator: str | None,
        destination: str | None,
        migration_signature: str | None,
        migration_slot: int | None,
        migration_at: datetime,
        meta: dict[str, Any] | None = None,
    ) -> UUID:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO migration_tracks (
                            mint, pool, creator, destination, migration_signature,
                            migration_slot, migration_at, status, meta
                        ) VALUES (
                            :mint, :pool, :creator, :destination, :sig,
                            :slot, :mat, 'active', CAST(:meta AS jsonb)
                        )
                        ON CONFLICT (mint) DO UPDATE SET
                            status = 'active',
                            pool = COALESCE(EXCLUDED.pool, migration_tracks.pool),
                            creator = COALESCE(EXCLUDED.creator, migration_tracks.creator)
                        RETURNING track_id
                        """
                    ),
                    {
                        "mint": mint,
                        "pool": pool,
                        "creator": creator,
                        "destination": destination,
                        "sig": migration_signature,
                        "slot": migration_slot,
                        "mat": migration_at,
                        "meta": __import__("orjson").dumps(meta or {}).decode(),
                    },
                )
            ).first()
            await session.commit()
            assert row is not None
            return row[0]

    async def complete_track(self, mint: str, *, status: TrackStatus = TrackStatus.COMPLETED) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE migration_tracks
                    SET status = :status, completed_at = now()
                    WHERE mint = :mint
                    """
                ),
                {"status": status.value, "mint": mint},
            )
            await session.commit()

    async def upsert_trade(self, trade: ObservedTrade) -> bool:
        """Insert trade if new. Returns True if inserted."""
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO wallet_trades (
                        mint, wallet, side, signature, traded_at, slot,
                        token_amount, sol_amount, usd_amount, price_usd,
                        is_early_buyer, early_rank, meta
                    ) VALUES (
                        :mint, :wallet, :side, :sig, :tat, :slot,
                        :token_amount, :sol_amount, :usd_amount, :price_usd,
                        :is_early, :early_rank, CAST(:meta AS jsonb)
                    )
                    ON CONFLICT (signature, wallet, side) DO UPDATE SET
                        is_early_buyer = wallet_trades.is_early_buyer
                            OR EXCLUDED.is_early_buyer,
                        early_rank = COALESCE(
                            EXCLUDED.early_rank, wallet_trades.early_rank
                        ),
                        sol_amount = COALESCE(
                            wallet_trades.sol_amount, EXCLUDED.sol_amount
                        ),
                        token_amount = COALESCE(
                            wallet_trades.token_amount, EXCLUDED.token_amount
                        )
                    RETURNING trade_id, (xmax = 0) AS was_insert
                    """
                ),
                {
                    "mint": trade.mint,
                    "wallet": trade.wallet,
                    "side": trade.side.value,
                    "sig": trade.signature,
                    "tat": trade.traded_at,
                    "slot": trade.slot,
                    "token_amount": trade.token_amount,
                    "sol_amount": trade.sol_amount,
                    "usd_amount": trade.usd_amount,
                    "price_usd": trade.price_usd,
                    "is_early": trade.is_early_buyer,
                    "early_rank": trade.early_rank,
                    "meta": __import__("orjson").dumps(trade.meta).decode(),
                },
            )
            row = result.first()
            inserted = bool(row and (row[1] if len(row) > 1 else True))
            if inserted:
                await self._apply_position(session, trade)
                await session.execute(
                    text(
                        """
                        UPDATE migration_tracks
                        SET trades_observed = trades_observed + 1
                        WHERE mint = :mint
                        """
                    ),
                    {"mint": trade.mint},
                )
            await session.commit()
            return inserted

    async def _apply_position(self, session: AsyncSession, trade: ObservedTrade) -> None:
        row = (
            await session.execute(
                text(
                    """
                    SELECT tokens_bought, tokens_sold, sol_spent, sol_received,
                           usd_spent, usd_received, trade_count, first_buy_at
                    FROM wallet_token_positions
                    WHERE wallet = :wallet AND mint = :mint
                    """
                ),
                {"wallet": trade.wallet, "mint": trade.mint},
            )
        ).mappings().first()

        if row:
            state = update_position_from_trade(
                tokens_bought=float(row["tokens_bought"] or 0),
                tokens_sold=float(row["tokens_sold"] or 0),
                sol_spent=float(row["sol_spent"] or 0),
                sol_received=float(row["sol_received"] or 0),
                usd_spent=float(row["usd_spent"] or 0),
                usd_received=float(row["usd_received"] or 0),
                trade=trade,
            )
            first_buy = row["first_buy_at"]
            if trade.side.value == "buy" and first_buy is None:
                first_buy = trade.traded_at
            await session.execute(
                text(
                    """
                    UPDATE wallet_token_positions SET
                        tokens_bought = :tb, tokens_sold = :ts,
                        tokens_remaining = :tr, sol_spent = :ss, sol_received = :sr,
                        usd_spent = :us, usd_received = :ur,
                        avg_entry_price_usd = :avg, realized_pnl_usd = :rp_usd,
                        realized_pnl_sol = :rp_sol, is_open = :open,
                        last_trade_at = :lt, first_buy_at = :fb,
                        trade_count = trade_count + 1, updated_at = now()
                    WHERE wallet = :wallet AND mint = :mint
                    """
                ),
                {
                    "tb": state["tokens_bought"],
                    "ts": state["tokens_sold"],
                    "tr": state["tokens_remaining"],
                    "ss": state["sol_spent"],
                    "sr": state["sol_received"],
                    "us": state["usd_spent"],
                    "ur": state["usd_received"],
                    "avg": state["avg_entry_price_usd"],
                    "rp_usd": state["realized_pnl_usd"],
                    "rp_sol": state["realized_pnl_sol"],
                    "open": state["is_open"],
                    "lt": trade.traded_at,
                    "fb": first_buy,
                    "wallet": trade.wallet,
                    "mint": trade.mint,
                },
            )
        else:
            state = update_position_from_trade(
                tokens_bought=0,
                tokens_sold=0,
                sol_spent=0,
                sol_received=0,
                usd_spent=0,
                usd_received=0,
                trade=trade,
            )
            await session.execute(
                text(
                    """
                    INSERT INTO wallet_token_positions (
                        wallet, mint, tokens_bought, tokens_sold, tokens_remaining,
                        sol_spent, sol_received, usd_spent, usd_received,
                        avg_entry_price_usd, realized_pnl_usd, realized_pnl_sol,
                        first_buy_at, last_trade_at, is_open, trade_count
                    ) VALUES (
                        :wallet, :mint, :tb, :ts, :tr, :ss, :sr, :us, :ur,
                        :avg, :rp_usd, :rp_sol, :fb, :lt, :open, 1
                    )
                    """
                ),
                {
                    "wallet": trade.wallet,
                    "mint": trade.mint,
                    "tb": state["tokens_bought"],
                    "ts": state["tokens_sold"],
                    "tr": state["tokens_remaining"],
                    "ss": state["sol_spent"],
                    "sr": state["sol_received"],
                    "us": state["usd_spent"],
                    "ur": state["usd_received"],
                    "avg": state["avg_entry_price_usd"],
                    "rp_usd": state["realized_pnl_usd"],
                    "rp_sol": state["realized_pnl_sol"],
                    "fb": trade.traded_at if trade.side.value == "buy" else None,
                    "lt": trade.traded_at,
                    "open": state["is_open"],
                },
            )

    async def save_early_buyers(
        self, track_id: UUID, mint: str, buyers: Sequence[ObservedTrade]
    ) -> int:
        """Persist ranked early buyers. Re-tracks replace ranks for the mint.

        Avoids UniqueViolation on (mint, rank) when ranking changes between runs.
        """
        n = 0
        async with self._sessions() as session:
            # Clear prior ranks for this mint so (mint, rank) stays unique
            await session.execute(
                text("DELETE FROM migration_buyers WHERE mint = :mint"),
                {"mint": mint},
            )
            for b in buyers:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO migration_buyers (
                            track_id, mint, wallet, rank, signature, bought_at,
                            slot, token_amount, sol_spent, usd_spent, entry_price_usd,
                            is_meaningful, meta
                        ) VALUES (
                            :track_id, :mint, :wallet, :rank, :sig, :bought_at,
                            :slot, :token_amount, :sol_spent, :usd_spent, :entry,
                            TRUE, CAST(:meta AS jsonb)
                        )
                        ON CONFLICT (mint, wallet) DO UPDATE SET
                            track_id = EXCLUDED.track_id,
                            rank = EXCLUDED.rank,
                            signature = EXCLUDED.signature,
                            bought_at = EXCLUDED.bought_at,
                            slot = EXCLUDED.slot,
                            token_amount = EXCLUDED.token_amount,
                            sol_spent = EXCLUDED.sol_spent,
                            usd_spent = EXCLUDED.usd_spent,
                            entry_price_usd = EXCLUDED.entry_price_usd,
                            is_meaningful = TRUE,
                            meta = EXCLUDED.meta
                        RETURNING id
                        """
                    ),
                    {
                        "track_id": track_id,
                        "mint": mint,
                        "wallet": b.wallet,
                        "rank": b.early_rank,
                        "sig": b.signature,
                        "bought_at": b.traded_at,
                        "slot": b.slot,
                        "token_amount": b.token_amount,
                        "sol_spent": b.sol_amount,
                        "usd_spent": b.usd_amount,
                        "entry": b.price_usd,
                        "meta": __import__("orjson").dumps(b.meta).decode(),
                    },
                )
                if result.first():
                    n += 1
            await session.execute(
                text(
                    """
                    UPDATE migration_tracks
                    SET buyers_captured = :n
                    WHERE track_id = :track_id
                    """
                ),
                {"n": n, "track_id": track_id},
            )
            await session.commit()
        return n

    async def save_market_snapshot(self, snap: MarketSnapshot) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO market_snapshots (
                        mint, captured_at, price_usd, liquidity_usd,
                        volume_m5_usd, volume_h1_usd, volume_h24_usd,
                        fdv_usd, market_cap_usd, pair_address, dex_id, source
                    ) VALUES (
                        :mint, :captured_at, :price, :liq, :m5, :h1, :h24,
                        :fdv, :mc, :pair, :dex, :source
                    )
                    """
                ),
                {
                    "mint": snap.mint,
                    "captured_at": snap.captured_at,
                    "price": snap.price_usd,
                    "liq": snap.liquidity_usd,
                    "m5": snap.volume_m5_usd,
                    "h1": snap.volume_h1_usd,
                    "h24": snap.volume_h24_usd,
                    "fdv": snap.fdv_usd,
                    "mc": snap.market_cap_usd,
                    "pair": snap.pair_address,
                    "dex": snap.dex_id,
                    "source": snap.source,
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE migration_tracks
                    SET snapshots_taken = snapshots_taken + 1
                    WHERE mint = :mint
                    """
                ),
                {"mint": snap.mint},
            )
            await session.commit()

    async def upsert_wallet_performance(self, perf: WalletPerformance) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO wallet_performance (
                        wallet, total_trades, total_buys, total_sells, tokens_purchased,
                        early_buy_count, qualifying_trades, wins, losses, loss_rate,
                        hit_rate, avg_return_pct, median_return_pct, max_return_pct,
                        avg_holding_seconds, realized_pnl_usd, realized_pnl_sol,
                        milestones_hit, updated_at
                    ) VALUES (
                        :wallet, :tt, :tb, :ts, :tp, :eb, :qt, :wins, :losses, :lr,
                        :hr, :avg, :med, :mx, :hold, :rp_usd, :rp_sol,
                        CAST(:ms AS jsonb), now()
                    )
                    ON CONFLICT (wallet) DO UPDATE SET
                        total_trades = EXCLUDED.total_trades,
                        total_buys = EXCLUDED.total_buys,
                        total_sells = EXCLUDED.total_sells,
                        tokens_purchased = EXCLUDED.tokens_purchased,
                        early_buy_count = EXCLUDED.early_buy_count,
                        qualifying_trades = EXCLUDED.qualifying_trades,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        loss_rate = EXCLUDED.loss_rate,
                        hit_rate = EXCLUDED.hit_rate,
                        avg_return_pct = EXCLUDED.avg_return_pct,
                        median_return_pct = EXCLUDED.median_return_pct,
                        max_return_pct = EXCLUDED.max_return_pct,
                        avg_holding_seconds = EXCLUDED.avg_holding_seconds,
                        realized_pnl_usd = EXCLUDED.realized_pnl_usd,
                        realized_pnl_sol = EXCLUDED.realized_pnl_sol,
                        milestones_hit = EXCLUDED.milestones_hit,
                        updated_at = now()
                    """
                ),
                {
                    "wallet": perf.wallet,
                    "tt": perf.total_trades,
                    "tb": perf.total_buys,
                    "ts": perf.total_sells,
                    "tp": perf.tokens_purchased,
                    "eb": perf.early_buy_count,
                    "qt": perf.qualifying_trades,
                    "wins": perf.wins,
                    "losses": perf.losses,
                    "lr": perf.loss_rate,
                    "hr": perf.hit_rate,
                    "avg": perf.avg_return_pct,
                    "med": perf.median_return_pct,
                    "mx": perf.max_return_pct,
                    "hold": perf.avg_holding_seconds,
                    "rp_usd": perf.realized_pnl_usd,
                    "rp_sol": perf.realized_pnl_sol,
                    "ms": __import__("orjson").dumps(perf.milestones_hit).decode(),
                },
            )
            await session.commit()

    async def load_trades_for_wallet(self, wallet: str) -> list[ObservedTrade]:
        from post_migration.models import TradeSide

        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT mint, wallet, side, signature, traded_at, slot,
                               token_amount, sol_amount, usd_amount, price_usd,
                               is_early_buyer, early_rank
                        FROM wallet_trades
                        WHERE wallet = :wallet
                        ORDER BY traded_at ASC
                        """
                    ),
                    {"wallet": wallet},
                )
            ).mappings().all()
        out: list[ObservedTrade] = []
        for r in rows:
            out.append(
                ObservedTrade(
                    mint=r["mint"],
                    wallet=r["wallet"],
                    side=TradeSide(r["side"]),
                    signature=r["signature"],
                    traded_at=r["traded_at"],
                    slot=r["slot"],
                    token_amount=float(r["token_amount"]) if r["token_amount"] is not None else None,
                    sol_amount=float(r["sol_amount"]) if r["sol_amount"] is not None else None,
                    usd_amount=float(r["usd_amount"]) if r["usd_amount"] is not None else None,
                    price_usd=float(r["price_usd"]) if r["price_usd"] is not None else None,
                    is_early_buyer=bool(r["is_early_buyer"]),
                    early_rank=r["early_rank"],
                )
            )
        return out

    async def list_wallets_with_trades(self, *, limit: int = 5000) -> list[str]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT wallet
                        FROM wallet_trades
                        ORDER BY wallet
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).fetchall()
            return [str(r[0]) for r in rows]

    async def recompute_all_performance(
        self,
        *,
        milestone_multiples: Sequence[float] | None = None,
        min_qualifying_sol: float | None = None,
        limit: int = 5000,
    ) -> int:
        """Rebuild wallet_performance from wallet_trades (replayable)."""
        from post_migration.config import settings
        from post_migration.performance import compute_wallet_performance

        multiples = milestone_multiples or [
            float(x.strip())
            for x in settings.milestone_multiples.split(",")
            if x.strip()
        ]
        min_sol = (
            min_qualifying_sol
            if min_qualifying_sol is not None
            else settings.min_meaningful_sol
        )
        wallets = await self.list_wallets_with_trades(limit=limit)
        n = 0
        for wallet in wallets:
            trades = await self.load_trades_for_wallet(wallet)
            if not trades:
                continue
            perf = compute_wallet_performance(
                wallet,
                trades,
                milestone_multiples=multiples,
                min_qualifying_sol=min_sol,
            )
            await self.upsert_wallet_performance(perf)
            n += 1
        logger.info("store.recompute_performance_done", wallets=n)
        return n

    async def migrations_needing_buyers(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Recent token.migrated events with zero rows in migration_buyers."""
        async with self._sessions() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT e.payload->>'mint' AS mint,
                               e.payload->>'pool' AS pool,
                               e.payload->>'creator' AS creator,
                               e.payload->>'destination' AS destination,
                               e.signature,
                               e.occurred_at,
                               e.payload
                        FROM events e
                        WHERE e.event_type = 'token.migrated'
                          AND e.payload->>'mint' IS NOT NULL
                          AND NOT EXISTS (
                              SELECT 1 FROM migration_buyers mb
                              WHERE mb.mint = e.payload->>'mint'
                          )
                        ORDER BY e.occurred_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            except Exception as exc:
                logger.warning("store.migrations_needing_buyers_failed", error=str(exc))
                return []
            return [dict(r) for r in result.mappings()]
