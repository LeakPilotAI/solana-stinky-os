"""Domain models for post-migration intelligence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradeClass(str, Enum):
    """Deterministic transaction classification (collect once, derive many)."""

    UNKNOWN = "unknown"
    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"
    LP = "lp"
    MIGRATION = "migration"
    BURN = "burn"
    PROGRAM = "program"
    POOL = "pool"
    FEE = "fee"


class TrackStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class ObservedTrade(BaseModel):
    """A single buy or sell observed after migration."""

    mint: str
    wallet: str
    side: TradeSide
    signature: str
    traded_at: datetime
    slot: int | None = None
    token_amount: float | None = None
    sol_amount: float | None = None
    usd_amount: float | None = None
    price_usd: float | None = None
    is_early_buyer: bool = False
    early_rank: int | None = None
    trade_class: TradeClass = TradeClass.UNKNOWN
    meta: dict[str, Any] = Field(default_factory=dict)

    def is_meaningful(self, min_sol: float) -> bool:
        if self.sol_amount is None:
            return True  # keep if unknown; filter only clear dust
        return abs(self.sol_amount) >= min_sol


class MarketSnapshot(BaseModel):
    mint: str
    captured_at: datetime
    price_usd: float | None = None
    liquidity_usd: float | None = None
    volume_m5_usd: float | None = None
    volume_h1_usd: float | None = None
    volume_h24_usd: float | None = None
    fdv_usd: float | None = None
    market_cap_usd: float | None = None
    pair_address: str | None = None
    dex_id: str | None = None
    source: str = "dexscreener"


class HolderSnapshot(BaseModel):
    mint: str
    captured_at: datetime
    holder_count: int | None = None
    top10_pct: float | None = None
    source: str = "rpc"
    meta: dict[str, Any] = Field(default_factory=dict)


class WalletPerformance(BaseModel):
    """Reusable performance record for Smart Money / scoring."""

    wallet: str
    total_trades: int = 0
    total_buys: int = 0
    total_sells: int = 0
    tokens_purchased: int = 0
    early_buy_count: int = 0
    qualifying_trades: int = 0
    wins: int = 0
    losses: int = 0
    loss_rate: float | None = None
    hit_rate: float | None = None
    avg_return_pct: float | None = None
    median_return_pct: float | None = None
    max_return_pct: float | None = None
    avg_holding_seconds: float | None = None
    realized_pnl_usd: float = 0.0
    realized_pnl_sol: float = 0.0
    milestones_hit: dict[str, int] = Field(default_factory=dict)


class MigrationTrack(BaseModel):
    track_id: UUID | None = None
    mint: str
    pool: str | None = None
    creator: str | None = None
    destination: str | None = None
    migration_signature: str | None = None
    migration_slot: int | None = None
    migration_at: datetime
    status: TrackStatus = TrackStatus.ACTIVE
    buyers_captured: int = 0
    trades_observed: int = 0
    snapshots_taken: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
