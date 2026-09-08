"""Recover measured post-migration completion boundaries from durable storage.

The post-migration collector commits ``migration_tracks.status='completed'`` before
publishing the Redis completion event. Redis/API delivery can fail independently,
so entity readiness must be able to recover from that durable fact without
fabricating an outcome or reconstructing a historical readiness snapshot.

When the durable track contains a complete measured market-snapshot path, the same
reconciliation seam also applies the canonical stinky-core RUNNER/HELD/FADE outcome
contract. Insufficient market evidence remains a generic ``completed`` boundary.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from entity_resolver.config import settings
from entity_resolver.launch_history import LaunchHistoryStore
from entity_resolver.measured_outcome_classification import (
    CLASSIFIED_OUTCOMES,
    classify_completed_market_path,
)

logger = structlog.get_logger(__name__)


class DurableOutcomeReconciler:
    """Reconcile durable completed tracks into measured outcomes and readiness capture."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        launch_history: LaunchHistoryStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._engine = create_async_engine(
            database_url or settings.database_url,
            pool_pre_ping=True,
            pool_size=2,
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._launch_history = launch_history or LaunchHistoryStore(database_url)
        self._owns_launch_history = launch_history is None
        self._http = http_client or httpx.AsyncClient(timeout=10.0)
        self._owns_http = http_client is None
        self._captured: set[tuple[str, str]] = set()
        self._running = False

    async def close(self) -> None:
        self._running = False
        await self._engine.dispose()
        if self._owns_launch_history:
            await self._launch_history.close()
        if self._owns_http:
            await self._http.aclose()

    async def _completed_candidates(self, *, limit: int = 500) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            mt.track_id,
                            mt.mint,
                            mt.migration_at,
                            mt.completed_at,
                            mt.buyers_captured,
                            mt.trades_observed,
                            mt.snapshots_taken,
                            el.entity_id,
                            el.outcome_status
                        FROM migration_tracks mt
                        JOIN entity_launches el ON el.mint = mt.mint
                        WHERE mt.status = 'completed'
                          AND mt.completed_at IS NOT NULL
                          AND el.entity_id IS NOT NULL
                        ORDER BY mt.completed_at DESC, mt.track_id DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": bounded},
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    async def _market_snapshots(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Read only snapshots captured inside the durable track boundary."""
        mint = str(row.get("mint") or "").strip()
        migration_at = row.get("migration_at")
        completed_at = row.get("completed_at")
        if not mint or not isinstance(migration_at, datetime) or not isinstance(completed_at, datetime):
            return []
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT captured_at, price_usd, liquidity_usd, volume_m5_usd
                        FROM market_snapshots
                        WHERE mint = :mint
                          AND captured_at >= :migration_at
                          AND captured_at <= :completed_at
                        ORDER BY captured_at ASC, snapshot_id ASC
                        LIMIT 2000
                        """
                    ),
                    {
                        "mint": mint,
                        "migration_at": migration_at,
                        "completed_at": completed_at,
                    },
                )
            ).mappings().all()
        return [dict(item) for item in rows]

    async def _classified_outcome(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return canonical measured classification or UNKNOWN on unavailable evidence."""
        try:
            snapshots = await self._market_snapshots(row)
            return classify_completed_market_path(row, snapshots)
        except Exception as exc:
            logger.warning(
                "entity.measured_outcome_classification_failed",
                mint=str(row.get("mint") or ""),
                error=str(exc)[:200],
            )
            return {
                "label": "UNKNOWN",
                "reason": "classification_evidence_unavailable",
                "evidence_only": True,
            }

    @staticmethod
    def _completion_metadata(row: dict[str, Any]) -> dict[str, object]:
        completed_at = row.get("completed_at")
        if isinstance(completed_at, datetime):
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=timezone.utc)
            completed_value: object = completed_at.isoformat()
        else:
            completed_value = str(completed_at) if completed_at is not None else None
        return {
            "evidence_basis": "durable_migration_track_completion",
            "track_id": str(row.get("track_id") or ""),
            "completed_at": completed_value,
            "buyers_captured": int(row.get("buyers_captured") or 0),
            "trades_observed": int(row.get("trades_observed") or 0),
            "snapshots_taken": int(row.get("snapshots_taken") or 0),
        }

    @classmethod
    def _classified_metadata(
        cls,
        row: dict[str, Any],
        classification: dict[str, Any],
    ) -> dict[str, object]:
        return {
            **cls._completion_metadata(row),
            "evidence_basis": "durable_completed_market_path_classification",
            "classification": classification,
        }

    async def _capture(self, mint: str, entity_id: str) -> bool:
        key = (mint, entity_id)
        if key in self._captured:
            return True
        base = settings.api_base_url.rstrip("/")
        try:
            response = await self._http.get(
                f"{base}/v1/entity-graph/investigation/{mint}/calibration",
                params={"entity_id": entity_id},
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "entity.durable_outcome_capture_failed",
                mint=mint,
                entity_id=entity_id,
                error=str(exc)[:200],
            )
            return False
        self._captured.add(key)
        logger.info(
            "entity.durable_outcome_capture_completed",
            mint=mint,
            entity_id=entity_id,
            status_code=response.status_code,
        )
        return True

    async def _reconcile_candidate(self, row: dict[str, Any]) -> bool:
        mint = str(row.get("mint") or "").strip()
        entity_id = str(row.get("entity_id") or "").strip()
        if not mint or not entity_id:
            return False

        existing_status = row.get("outcome_status")
        if existing_status not in (None, "completed"):
            # A richer measured outcome already exists. Never downgrade or reclassify it.
            return False

        completed_at = row.get("completed_at")
        if isinstance(completed_at, datetime):
            observed_at = completed_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
        else:
            return False

        classification = await self._classified_outcome(row)
        measured_label = str(classification.get("label") or "UNKNOWN").upper()
        if measured_label in CLASSIFIED_OUTCOMES:
            changed = await self._launch_history.record_outcome(
                mint=mint,
                status=measured_label,
                metadata=self._classified_metadata(row, classification),
                observed_at=observed_at,
            )
            if changed:
                logger.info(
                    "entity.measured_outcome_recorded",
                    mint=mint,
                    entity_id=entity_id,
                    outcome=measured_label,
                    reason=classification.get("reason"),
                    evidence_basis="completed_market_snapshot_path",
                )
        elif existing_status is None:
            # Completion is still real evidence even when the measured path is not
            # sufficient for RUNNER/HELD/FADE. Preserve UNKNOWN performance semantics.
            await self._launch_history.record_outcome(
                mint=mint,
                status="completed",
                metadata={
                    **self._completion_metadata(row),
                    "classification": classification,
                    "performance_outcome": "UNKNOWN",
                },
                observed_at=observed_at,
            )

        # Capture after any classification promotion so readiness sees the richer
        # measured outcome in the same prospective evidence boundary. Semantic hash
        # dedup remains the durable authority; no historical snapshot is backdated.
        return await self._capture(mint, entity_id)

    async def reconcile_once(self, *, limit: int = 500) -> dict[str, int]:
        try:
            rows = await self._completed_candidates(limit=limit)
        except Exception as exc:
            logger.warning(
                "entity.durable_outcome_scan_failed",
                error=str(exc)[:200],
            )
            return {"candidates": 0, "captured": 0}

        captured = 0
        for row in rows:
            try:
                if await self._reconcile_candidate(row):
                    captured += 1
            except Exception as exc:
                logger.warning(
                    "entity.durable_outcome_reconcile_failed",
                    mint=str(row.get("mint") or ""),
                    error=str(exc)[:200],
                )
        if rows:
            logger.info(
                "entity.durable_outcome_reconciliation",
                candidates=len(rows),
                captured=captured,
            )
        return {"candidates": len(rows), "captured": captured}

    async def run_forever(self) -> None:
        self._running = True
        try:
            # Startup recovery closes the gap for completions whose stream event was
            # lost before this resolver process began, and can promote previously
            # generic completion boundaries when their measured path is sufficient.
            await self.reconcile_once()
            interval = max(10.0, float(settings.batch_interval_sec))
            while self._running:
                await asyncio.sleep(interval)
                await self.reconcile_once()
        finally:
            await self.close()
