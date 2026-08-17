"""Domain models for detected launches and migrations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DetectedLaunch(BaseModel):
    """A newly detected token launch on Solana."""

    mint: str
    deployer: str
    name: str | None = None
    symbol: str | None = None
    uri: str | None = None
    bonding_curve: str | None = None
    signature: str | None = None
    slot: int | None = None
    block_time: datetime | None = None
    source: str = "unknown"
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "deployer": self.deployer,
            "name": self.name,
            "symbol": self.symbol,
            "uri": self.uri,
            "bonding_curve": self.bonding_curve,
            "source": self.source,
        }


class DetectedMigration(BaseModel):
    """A token that just graduated from pump.fun bonding curve to PumpSwap."""

    mint: str
    pool: str
    creator: str | None = None
    quote_mint: str | None = None
    base_amount_in: int | None = None
    quote_amount_in: int | None = None
    lp_mint: str | None = None
    signature: str | None = None
    slot: int | None = None
    block_time: datetime | None = None
    destination: str = "pumpswap"
    source: str = "pump.fun-migrate"
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "pool": self.pool,
            "creator": self.creator,
            "quote_mint": self.quote_mint,
            "base_amount_in": self.base_amount_in,
            "quote_amount_in": self.quote_amount_in,
            "lp_mint": self.lp_mint,
            "destination": self.destination,
            "source": self.source,
        }


class WalletSummary(BaseModel):
    """Minimal historical summary for a creator wallet."""

    address: str
    first_seen: datetime | None = None
    launch_count: int = 0
    recent_mints: list[str] = Field(default_factory=list)
    note: str | None = None
