"""Persistent market-lifecycle outcome observations.

This module stores measured market observations at explicit horizons. It does
not classify a token as good/bad, predict returns, or turn observations into
trading authority. Missing measurements remain UNKNOWN to downstream layers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings


HORIZONS_SECONDS: dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "24h": 86400,
}


def normalize_horizon(horizon: str | int) -> tuple[str, int] | None:
    """Return a canonical supported horizon or None for unknown input."""
    if isinstance(horizon, bool):
        return None
    if isinstance(horizon, int):
        for name, seconds in HORIZONS_SECONDS.items():
            if horizon == seconds:
                return name, seconds
        return None
    value = str(horizon).strip().lower()
    seconds = HORIZONS_SECONDS.get(value)
    if seconds is None:
        return None
    return value, seconds


class MarketOutcomeStore:
    """Persist bounded, timestamped market outcome observations."""

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

        path = Path(__file__).resolve().parents[2] / "migrations" / "007_market_outcome_observations.sql"
        if not path.exists():
            raise FileNotFoundError(f"market outcome migration missing: {path}")
        sql = path.read_text(encoding="utf-8")
        async with self._sessions() as session:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await session.execute(text(statement))
            await session.commit()

    async def record_observation(
        self,
        *,
        mint: str,
        horizon: str | int,
        observed_at: datetime,
        metrics: dict[str, Any] | None = None,
        source: str,
        evidence_basis: str,
        anchor_observed_at: datetime | None = None,
        event_id: str | None = None,
        signature: str | None = None,
        ingested_at: datetime | None = None,
    ) -> bool:
        """Persist one measured lifecycle observation idempotently."""
        mint = str(mint or "").strip()
        source = str(source or "").strip()
        evidence_basis = str(evidence_basis or "").strip()
        normalized = normalize_horizon(horizon)
        if not mint or not source or not evidence_basis or normalized is None:
            return False
        if not isinstance(observed_at, datetime):
            return False
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        if anchor_observed_at is not None and anchor_observed_at.tzinfo is None:
            anchor_observed_at = anchor_observed_at.replace(tzinfo=timezone.utc)
        if ingested_at is None:
            ingested_at = datetime.now(timezone.utc)
        elif ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=timezone.utc)

        horizon_name, horizon_seconds = normalized
        payload = metrics if isinstance(metrics, dict) else {}
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO market_outcome_observations (
                            mint, horizon, horizon_seconds, anchor_observed_at,
                            observed_at, ingested_at, source, evidence_basis,
                            metrics, event_id, signature
                        ) VALUES (
                            :mint, :horizon, :horizon_seconds, :anchor_observed_at,
                            :observed_at, :ingested_at, :source, :evidence_basis,
                            CAST(:metrics AS jsonb), :event_id, :signature
                        )
                        ON CONFLICT DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "mint": mint,
                        "horizon": horizon_name,
                        "horizon_seconds": horizon_seconds,
                        "anchor_observed_at": anchor_observed_at,
                        "observed_at": observed_at,
                        "ingested_at": ingested_at,
                        "source": source,
                        "evidence_basis": evidence_basis,
                        "metrics": orjson.dumps(payload).decode(),
                        "event_id": event_id,
                        "signature": signature,
                    },
                )
            ).first()
            if not row:
                await session.rollback()
                return False
            await session.commit()
            return True

    async def list_mint_observations(
        self,
        *,
        mint: str,
        limit: int = 100,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded lifecycle evidence, optionally at a historical cutoff."""
        bounded_limit = max(1, min(int(limit), 500))
        params: dict[str, Any] = {"mint": str(mint).strip(), "limit": bounded_limit}
        cutoff_clause = ""
        if as_of is not None:
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
            cutoff_clause = "AND observed_at <= :as_of"
            params["as_of"] = as_of
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT id, mint, horizon, horizon_seconds, anchor_observed_at,
                               observed_at, ingested_at, source, evidence_basis,
                               metrics, event_id, signature, created_at
                        FROM market_outcome_observations
                        WHERE mint = :mint
                          {cutoff_clause}
                        ORDER BY observed_at ASC, horizon_seconds ASC, id ASC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).mappings().all()
            return [dict(row) for row in rows]
