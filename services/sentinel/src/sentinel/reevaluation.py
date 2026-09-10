"""Temporal-safe evidence-driven re-evaluation for Gate-1 intelligence.

A first decision that was INTELLIGENCE_INSUFFICIENT remains immutable.  During
its existing live watch, a mint may receive a new decision only after durable
wallet/creator evidence has materially changed.  No clock threshold is invented,
UNKNOWN is never promoted, and the normal investigation/admission path is reused.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text

from sentinel.volume import VolumeMonitor, VolumeSnapshot
from sentinel.models import DetectedMigration

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EvidenceSignature:
    early_buyers: int
    qualifying_wallets: int
    creator_launches: int

    @property
    def has_admission_evidence(self) -> bool:
        return self.qualifying_wallets > 0 or self.creator_launches >= 3


class ReevaluatingVolumeMonitor(VolumeMonitor):
    """Volume monitor that re-runs UNKNOWN intelligence only on new evidence."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_reevaluation_signature: dict[str, EvidenceSignature] = {}
        self._alerted_mints: set[str] = set()

    async def _latest_insufficient(self, mint: str) -> bool:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT alert_ok, alert_reason
                        FROM market_inspections
                        WHERE mint = :mint
                        ORDER BY inspected_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"mint": mint},
                )
            ).mappings().first()
        return bool(
            row
            and row.get("alert_ok") is not True
            and row.get("alert_reason") == "INTELLIGENCE_INSUFFICIENT"
        )

    async def _evidence_signature(
        self, mint: str, creator: str | None
    ) -> EvidenceSignature:
        async with self._sessions() as session:
            buyer_row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          count(DISTINCT mb.wallet) AS early_buyers,
                          count(DISTINCT mb.wallet) FILTER (
                            WHERE COALESCE(wp.early_buy_count,0) >= 3
                              AND COALESCE(wp.tokens_purchased,0) >= 3
                              AND (wp.hit_rate IS NOT NULL OR COALESCE(wp.early_success_sample,0) >= 3)
                          ) AS qualifying_wallets
                        FROM migration_buyers mb
                        LEFT JOIN wallet_performance wp ON wp.wallet=mb.wallet
                        WHERE mb.mint=:mint
                        """
                    ),
                    {"mint": mint},
                )
            ).mappings().one()
            launches = 0
            if creator:
                launches = int(
                    (
                        await session.execute(
                            text(
                                """
                                SELECT max(COALESCE(e.launch_count,0))
                                FROM entity_wallets ew
                                JOIN entities e ON e.entity_id=ew.entity_id
                                WHERE ew.wallet=:creator
                                """
                            ),
                            {"creator": creator},
                        )
                    ).scalar_one_or_none()
                    or 0
                )
        return EvidenceSignature(
            early_buyers=int(buyer_row.get("early_buyers") or 0),
            qualifying_wallets=int(buyer_row.get("qualifying_wallets") or 0),
            creator_launches=launches,
        )

    async def _record_followup_tick(
        self, migration: DetectedMigration, snap: VolumeSnapshot
    ) -> None:
        # Preserve the existing observation/quality path first.
        await super()._record_followup_tick(migration, snap)
        mint = migration.mint
        if mint in self._alerted_mints:
            return
        try:
            if not await self._latest_insufficient(mint):
                return
            current = await self._evidence_signature(mint, migration.creator)
            previous = self._last_reevaluation_signature.get(mint)
            if previous == current:
                return
            self._last_reevaluation_signature[mint] = current
            if not current.has_admission_evidence:
                return

            await self._trace(
                mint=mint,
                kind="intelligence_reevaluation",
                message="New durable intelligence evidence triggered a fresh decision",
                extra={
                    "early_buyers": current.early_buyers,
                    "qualifying_wallets": current.qualifying_wallets,
                    "creator_launches": current.creator_launches,
                    "previous_decision_preserved": True,
                    "thresholds_changed": False,
                },
            )
            emitted = await self._investigate_and_maybe_alert(migration, snap)
            if emitted:
                self._alerted_mints.add(mint)
            logger.info(
                "intelligence.reevaluated",
                mint=mint,
                emitted=bool(emitted),
                early_buyers=current.early_buyers,
                qualifying_wallets=current.qualifying_wallets,
                creator_launches=current.creator_launches,
                previous_decision_preserved=True,
            )
        except Exception as exc:
            # Fail closed: a re-evaluation failure never becomes an alert.
            logger.warning(
                "intelligence.reevaluation_failed",
                mint=mint,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
