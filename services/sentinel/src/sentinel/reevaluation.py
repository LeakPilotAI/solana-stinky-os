"""Temporal-safe evidence-driven re-evaluation for Gate-1 intelligence.

A first decision that was INTELLIGENCE_INSUFFICIENT remains immutable. During
its existing live watch, a mint may receive a new decision only after durable
wallet/creator evidence has materially changed. No clock threshold is invented,
UNKNOWN is never promoted, and the normal intelligence/admission rules remain
authoritative.

The post-migration learner stores labeled early-buyer outcome history in
wallet_performance as early_success_rate / early_success_sample.  The core
intelligence layer names the same concepts hit_rate / sample_resolved.  This
module performs that explicit vocabulary adaptation for prospective
re-evaluations; it never invents or backfills evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import structlog
from sqlalchemy import text

from stinky_core.events.base import Event, EventType
from stinky_core.intelligence import (
    INTEL_VERSION,
    can_alert_investigation,
    inspection_persist_params,
    investigate,
)
from sentinel.volume import VolumeMonitor, VolumeSnapshot, resolve_global_fees
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


def normalize_wallet_performance_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map persisted labeled-outcome fields into core wallet-intel vocabulary.

    `early_success_sample` is populated from wallet_early_success.sample_size and
    `early_success_rate` from wallet_early_success.success_rate by the
    post-migration learner.  They are measured historical outcomes, not inferred
    values. Existing native core fields always win when present.
    """
    out = dict(row)
    sample = out.get("early_success_sample")
    success_rate = out.get("early_success_rate")
    early_runner = out.get("early_on_runner")

    if out.get("sample_resolved") is None and sample is not None:
        out["sample_resolved"] = sample
    if out.get("sample_size") is None and sample is not None:
        out["sample_size"] = sample
    if out.get("hit_rate") is None and success_rate is not None:
        out["hit_rate"] = success_rate
    if out.get("runners") is None and early_runner is not None:
        out["runners"] = early_runner
    return out


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
                              AND (
                                wp.hit_rate IS NOT NULL
                                OR (
                                  COALESCE(wp.early_success_sample,0) >= 3
                                  AND wp.early_success_rate IS NOT NULL
                                )
                              )
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

    async def _load_reevaluation_wallet_history(
        self, mint: str
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Load only durable buyer/performance rows visible at re-evaluation time."""
        buyers_rows: list[dict[str, Any]] = []
        perf_map: dict[str, dict[str, Any]] = {}
        async with self._sessions() as session:
            buyers = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, rank, sol_spent
                        FROM migration_buyers
                        WHERE mint = :mint
                        ORDER BY rank ASC
                        LIMIT 40
                        """
                    ),
                    {"mint": mint},
                )
            ).mappings().all()
            buyers_rows = [dict(b) for b in buyers]
            wallets = [b["wallet"] for b in buyers_rows if b.get("wallet")]
            if wallets:
                perf_rows = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet, early_buy_count, hit_rate, avg_return_pct,
                                   tokens_purchased, early_success_rate,
                                   early_success_sample, early_on_runner, early_on_mega
                            FROM wallet_performance
                            WHERE wallet = ANY(:wallets)
                            """
                        ),
                        {"wallets": wallets},
                    )
                ).mappings().all()
                perf_map = {
                    str(r["wallet"]): normalize_wallet_performance_row(dict(r))
                    for r in perf_rows
                }
        return buyers_rows, perf_map

    async def _reevaluate_with_complete_wallet_history(
        self, migration: DetectedMigration, snap: VolumeSnapshot
    ) -> bool:
        """Run a fresh prospective decision using complete persisted wallet history.

        This does not mutate the original decision.  It uses a new decision time,
        re-runs the same core investigate/can_alert rules, persists the new
        inspection, and calls the existing alert emitter only if those rules pass.
        """
        mint = migration.mint
        await self._hydrate_memory()

        obs = await resolve_global_fees(
            mint, protocol=snap.dex_id, pool=snap.pair_address
        )
        await self._persist_fee_observation(obs)
        fees_sol = obs.global_fees_sol if obs.fees_verified else None
        snap.fees_sol = fees_sol
        fee_status = "VERIFIED" if obs.fees_verified else "UNKNOWN"

        smart = await self._load_smart_money(mint)
        entity = await self._load_entity(migration.creator)
        buyers_rows, perf_map = await self._load_reevaluation_wallet_history(mint)

        creator_profile = None
        if entity.entity_id:
            creator_profile = {
                "entity_id": entity.entity_id,
                "launch_count": entity.launch_count,
                "wallet_count": entity.wallet_count,
                "known": True,
            }

        decision_timestamp = datetime.now(timezone.utc).isoformat()
        bundle: dict[str, Any] = {
            "mint": mint,
            "volume_m5_usd": snap.volume_m5_usd,
            "volume_usd": snap.volume_m5_usd,
            "liquidity_usd": snap.liquidity_usd,
            "market_cap_usd": getattr(snap, "market_cap_usd", None),
            "price_usd": snap.price_usd,
            "txns_m5_buys": snap.txns_m5_buys,
            "txns_m5_sells": snap.txns_m5_sells,
            "buyers": buyers_rows or None,
            "wallet_performance": perf_map or None,
            "wallets_as_of_decision": True,
            "creator_profile": creator_profile,
            "creator": migration.creator,
            "fee_status": fee_status,
            "global_fees_sol": fees_sol,
            "volume_gate": self._gate1_volume(),
            "decision_timestamp": decision_timestamp,
        }
        inv = investigate(bundle, memory=getattr(self, "_memory", None))

        mem = getattr(self, "_memory", None)
        if mem is not None:
            try:
                mem.ingest_decision(
                    mint=mint,
                    observed_at=decision_timestamp,
                    buyers=buyers_rows,
                    creator=migration.creator,
                    fingerprint=inv.fingerprint,
                    features=inv.fingerprint_features,
                )
                if inv.investigation_record:
                    rec = dict(inv.investigation_record)
                    rec["evidence_label"] = "LIVE"
                    mem.record_investigation(rec)
                mem.record_market_tick(
                    mint=mint,
                    observed_at=decision_timestamp,
                    volume_m5_usd=snap.volume_m5_usd,
                    price_usd=snap.price_usd,
                    liquidity_usd=snap.liquidity_usd,
                    market_cap_usd=getattr(snap, "market_cap_usd", None),
                    buys=snap.txns_m5_buys,
                    sells=snap.txns_m5_sells,
                    txns=(snap.txns_m5_buys or 0) + (snap.txns_m5_sells or 0)
                    if snap.txns_m5_buys is not None or snap.txns_m5_sells is not None
                    else None,
                )
                await self._persist_memory_decision(
                    mint=mint,
                    observed_at=decision_timestamp,
                    buyers=buyers_rows,
                    creator=migration.creator,
                    fingerprint=inv.fingerprint,
                    features=inv.fingerprint_features,
                    volume_m5_usd=snap.volume_m5_usd,
                    price_usd=snap.price_usd,
                    liquidity_usd=snap.liquidity_usd,
                    market_cap_usd=getattr(snap, "market_cap_usd", None),
                    buys=snap.txns_m5_buys,
                    sells=snap.txns_m5_sells,
                    investigation=inv.investigation_record,
                )
            except Exception as exc:
                logger.debug(
                    "intelligence.reevaluation_memory_persist_failed",
                    mint=mint,
                    error=str(exc)[:200],
                )

        alert_ok, alert_reason = can_alert_investigation(True, inv)
        if alert_ok:
            inv.pipeline_status = "ALERT"
        await self._persist_inspection(
            inspection_persist_params(inv, alert_ok=alert_ok, alert_reason=alert_reason)
        )
        await self._persist_intelligence_decision(
            inv, snap, alert_ok=alert_ok, alert_reason=alert_reason
        )

        try:
            insp_event = Event(
                event_type=EventType.MARKET_INSPECTION_COMPLETED,
                signature=migration.signature,
                block_time=datetime.now(timezone.utc),
                payload={
                    "mint": mint,
                    "pipeline_status": inv.pipeline_status,
                    "stinky_score": inv.score.score,
                    "confidence": inv.score.confidence,
                    "synthetic_level": inv.synthetic.level,
                    "rug_level": inv.rug.level,
                    "runner_potential": inv.runner.score,
                    "has_intelligence": inv.has_intelligence,
                    "fee_status": inv.fee_status,
                    "global_fees_sol": inv.global_fees_sol,
                    "alert_ok": alert_ok,
                    "alert_reason": alert_reason,
                    "model_version": INTEL_VERSION,
                    "reevaluation": True,
                },
                producer="sentinel-volume",
            )
            await self._publisher.publish_raw_event(insp_event, kind="inspection")
        except Exception as exc:
            logger.debug(
                "intelligence.reevaluation_event_publish_failed",
                mint=mint,
                error=str(exc)[:200],
            )

        logger.info(
            "intelligence.reevaluation_complete",
            mint=mint,
            has_intelligence=inv.has_intelligence,
            alert_ok=alert_ok,
            alert_reason=alert_reason,
            wallet_status=inv.wallets.status,
            smart_wallet_count=inv.wallets.smart_wallet_count,
            previous_decision_preserved=True,
        )
        if not alert_ok:
            return False

        await self._emit_alert(migration, snap, obs, inv, smart, entity)
        return True

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
                    "wallet_history_adapter": "early-success-v1",
                },
            )
            emitted = await self._reevaluate_with_complete_wallet_history(
                migration, snap
            )
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
