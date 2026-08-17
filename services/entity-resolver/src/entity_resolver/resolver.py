"""Deterministic entity resolution rules (ADR-005).

Rules (v0.2 co-buy clusters):
1. Every deployer wallet becomes (or joins) an entity.
2. Launch count on that entity is tracked from events.
3. Early buyers that co-appear on ≥ N mints are linked with tiered confidence.
4. Never invent links without an explicit reason string.
5. Auto-merge two entities only when shared early mints ≥ auto_merge_min_shared and confidence ≥ auto_merge_min_confidence (safe, auditable).
"""

from __future__ import annotations

import structlog

from entity_resolver.config import settings
from entity_resolver.store import EntityStore

logger = structlog.get_logger(__name__)


def co_buy_confidence(shared_mints: int) -> tuple[float, str]:
    """Tiered confidence from shared early-buy mints (deterministic)."""
    if shared_mints >= 8:
        return 0.85, "strong_co_early_buy"
    if shared_mints >= 5:
        return 0.70, "co_early_buy"
    if shared_mints >= settings.min_co_buy_overlap:
        return settings.co_buy_link_confidence, "co_early_buy"
    return 0.0, "insufficient_overlap"


class EntityResolver:
    def __init__(self, store: EntityStore | None = None) -> None:
        self._store = store or EntityStore()

    async def close(self) -> None:
        await self._store.close()

    async def run_batch(self) -> dict[str, int]:
        """Full deterministic pass over known deployers + co-buy pairs."""
        stats = {
            "deployers_seen": 0,
            "entities_created": 0,
            "co_buy_links": 0,
            "co_buy_skipped": 0,
            "co_buy_pairs_seen": 0,
            "strong_links": 0,
            "entity_merges": 0,
        }

        deployers = await self._store.deployers_from_events()
        for d in deployers:
            wallet = d.get("deployer")
            if not wallet:
                continue
            stats["deployers_seen"] += 1
            existing = await self._store.get_entity_for_wallet(wallet)
            if existing:
                continue
            entity_id = await self._store.create_entity(
                primary_wallet=wallet,
                entity_type="deployer",
                display_label=f"dep:{wallet[:6]}",
                confidence=settings.deployer_link_confidence,
                meta={
                    "launches": d.get("launches"),
                    "first_seen": str(d.get("first_seen")),
                },
            )
            stats["entities_created"] += 1
            logger.info(
                "entity.created",
                entity_id=str(entity_id),
                wallet=wallet,
                reason="deployer_from_events",
            )

        pairs = await self._store.early_buyer_pairs(settings.min_co_buy_overlap)
        for p in pairs:
            a, b = p["wallet_a"], p["wallet_b"]
            shared = int(p["shared_mints"])
            stats["co_buy_pairs_seen"] += 1
            conf, reason = co_buy_confidence(shared)
            if conf <= 0:
                stats["co_buy_skipped"] += 1
                continue

            ea = await self._store.get_entity_for_wallet(a)
            eb = await self._store.get_entity_for_wallet(b)

            if ea and eb:
                if ea["entity_id"] == eb["entity_id"]:
                    continue
                # Safe auto-merge only with strong evidence (shared >= threshold)
                if (
                    settings.auto_merge_enabled
                    and shared >= settings.auto_merge_min_shared
                    and conf >= settings.auto_merge_min_confidence
                ):
                    # Survivor = more launches, then more wallets, then stable id order
                    la = int(ea.get("launch_count") or 0)
                    lb = int(eb.get("launch_count") or 0)
                    wa = int(ea.get("wallet_count") or 0)
                    wb = int(eb.get("wallet_count") or 0)
                    if (lb, wb, str(eb["entity_id"])) > (la, wa, str(ea["entity_id"])):
                        survivor, absorbed = eb, ea
                    else:
                        survivor, absorbed = ea, eb
                    ok = await self._store.merge_entities(
                        survivor_id=survivor["entity_id"],
                        absorbed_id=absorbed["entity_id"],
                        reason="strong_co_early_buy_merge",
                        confidence=conf,
                        evidence={
                            "shared_mints": shared,
                            "wallet_a": a,
                            "wallet_b": b,
                            "rule": "auto_merge_min_shared",
                        },
                    )
                    if ok:
                        stats["entity_merges"] = stats.get("entity_merges", 0) + 1
                        stats["strong_links"] += 1
                        logger.info(
                            "entity.merged",
                            survivor=str(survivor["entity_id"]),
                            absorbed=str(absorbed["entity_id"]),
                            shared_mints=shared,
                            confidence=conf,
                        )
                    else:
                        stats["co_buy_skipped"] += 1
                    continue
                stats["co_buy_skipped"] += 1
                logger.debug(
                    "entity.co_buy_skip_merge",
                    wallet_a=a,
                    wallet_b=b,
                    shared_mints=shared,
                    entity_a=str(ea["entity_id"]),
                    entity_b=str(eb["entity_id"]),
                )
                continue

            if ea and not eb:
                ok = await self._store.link_wallet(
                    entity_id=ea["entity_id"],
                    wallet=b,
                    role="early_buyer",
                    reason=reason,
                    confidence=conf,
                    evidence={"shared_mints": shared, "peer": a},
                )
                if ok:
                    stats["co_buy_links"] += 1
                    if shared >= 8:
                        stats["strong_links"] += 1
                    await self._store.bump_early_buy_count(ea["entity_id"])
                    logger.info(
                        "entity.co_buy_linked",
                        entity_id=str(ea["entity_id"]),
                        wallet=b,
                        peer=a,
                        shared_mints=shared,
                        confidence=conf,
                        reason=reason,
                    )
                else:
                    stats["co_buy_skipped"] += 1
            elif eb and not ea:
                ok = await self._store.link_wallet(
                    entity_id=eb["entity_id"],
                    wallet=a,
                    role="early_buyer",
                    reason=reason,
                    confidence=conf,
                    evidence={"shared_mints": shared, "peer": b},
                )
                if ok:
                    stats["co_buy_links"] += 1
                    if shared >= 8:
                        stats["strong_links"] += 1
                    await self._store.bump_early_buy_count(eb["entity_id"])
                    logger.info(
                        "entity.co_buy_linked",
                        entity_id=str(eb["entity_id"]),
                        wallet=a,
                        peer=b,
                        shared_mints=shared,
                        confidence=conf,
                        reason=reason,
                    )
                else:
                    stats["co_buy_skipped"] += 1
            else:
                # neither has entity — create cluster for A, link B
                eid = await self._store.create_entity(
                    primary_wallet=a,
                    entity_type="trader",
                    display_label=f"tr:{a[:6]}",
                    confidence=conf,
                    meta={"seed": reason, "shared_mints_seed": shared},
                )
                stats["entities_created"] += 1
                ok = await self._store.link_wallet(
                    entity_id=eid,
                    wallet=b,
                    role="early_buyer",
                    reason=reason,
                    confidence=conf,
                    evidence={"shared_mints": shared, "peer": a},
                )
                if ok:
                    stats["co_buy_links"] += 1
                    if shared >= 8:
                        stats["strong_links"] += 1
                    await self._store.bump_early_buy_count(eid)
                    logger.info(
                        "entity.cluster_seeded",
                        entity_id=str(eid),
                        wallet_a=a,
                        wallet_b=b,
                        shared_mints=shared,
                        confidence=conf,
                        reason=reason,
                    )

        logger.info("entity.batch_complete", **stats)
        return stats

    async def on_deployer_observed(self, deployer: str) -> str:
        """Ensure deployer has an entity; return entity_id as str."""
        eid = await self._store.ensure_wallet_entity(
            deployer,
            entity_type="deployer",
            confidence=settings.deployer_link_confidence,
        )
        await self._store.bump_launch_count(eid)
        return str(eid)
