"""Historical bridge from measured migration tracks into canonical entity launch memory.

The bridge is deliberately conservative. It only links a historical migration to an
entity when the creator/deployer relationship was already observed by the migration
time. Original migration time is preserved as observed_at; current insertion time
remains the ingestion boundary through entity_launches.created_at.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "HISTORICAL_RESEARCH_BRIDGE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}

_REQUIRED_TABLES = (
    "migration_tracks",
    "entity_launches",
    "entities",
    "entity_wallets",
    "developer_longitudinal_snapshots",
    "developer_correlation_snapshots",
    "market_outcome_observations",
    "events",
)


async def historical_research_bridge_preflight(session: AsyncSession) -> dict[str, Any]:
    """Return bounded factual inventory for the Phase-10 historical research path."""
    try:
        row = (await session.execute(text("""
            SELECT
              to_regclass('migration_tracks')::text AS migration_tracks,
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('entities')::text AS entities,
              to_regclass('entity_wallets')::text AS entity_wallets,
              to_regclass('developer_longitudinal_snapshots')::text AS developer_longitudinal_snapshots,
              to_regclass('developer_correlation_snapshots')::text AS developer_correlation_snapshots,
              to_regclass('market_outcome_observations')::text AS market_outcome_observations,
              to_regclass('events')::text AS events
        """))).mappings().first()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "tables": {},
            "counts": {},
            "missing_tables": list(_REQUIRED_TABLES),
            "failure_stage": "table_preflight",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    table_state = {name: bool(row and row.get(name)) for name in _REQUIRED_TABLES}
    missing_tables = [name for name, exists in table_state.items() if not exists]
    counts: dict[str, int | None] = {}

    count_sql = {
        "migration_tracks": "SELECT COUNT(*)::int FROM migration_tracks",
        "migration_tracks_with_creator": "SELECT COUNT(*)::int FROM migration_tracks WHERE creator IS NOT NULL AND btrim(creator) <> ''",
        "entity_launches": "SELECT COUNT(*)::int FROM entity_launches",
        "entity_launches_with_mint": "SELECT COUNT(*)::int FROM entity_launches WHERE mint IS NOT NULL AND btrim(mint) <> ''",
        "developer_longitudinal_snapshots": "SELECT COUNT(*)::int FROM developer_longitudinal_snapshots",
        "developer_correlation_snapshots": "SELECT COUNT(*)::int FROM developer_correlation_snapshots",
        "market_outcome_observations": "SELECT COUNT(*)::int FROM market_outcome_observations",
        "tracking_completed_events": "SELECT COUNT(*)::int FROM events WHERE event_type = 'post_migration.tracking_completed'",
    }
    dependencies = {
        "migration_tracks": "migration_tracks",
        "migration_tracks_with_creator": "migration_tracks",
        "entity_launches": "entity_launches",
        "entity_launches_with_mint": "entity_launches",
        "developer_longitudinal_snapshots": "developer_longitudinal_snapshots",
        "developer_correlation_snapshots": "developer_correlation_snapshots",
        "market_outcome_observations": "market_outcome_observations",
        "tracking_completed_events": "events",
    }
    for key, sql in count_sql.items():
        if not table_state.get(dependencies[key], False):
            counts[key] = None
            continue
        try:
            value = (await session.execute(text(sql))).scalar()
            counts[key] = int(value or 0)
        except Exception:
            counts[key] = None

    bridge_counts = {
        "historically_resolvable_migrations": None,
        "unbridged_historically_resolvable_migrations": None,
    }
    if all(table_state.get(name, False) for name in ("migration_tracks", "entity_launches", "entities", "entity_wallets")):
        try:
            bridge_row = (await session.execute(text("""
                WITH resolved AS (
                    SELECT mt.mint
                    FROM migration_tracks mt
                    LEFT JOIN LATERAL (
                        SELECT ew.entity_id
                        FROM entity_wallets ew
                        WHERE ew.wallet = mt.creator
                          AND ew.first_seen_at IS NOT NULL
                          AND ew.first_seen_at <= mt.migration_at
                        ORDER BY ew.first_seen_at ASC, ew.id ASC
                        LIMIT 1
                    ) ew ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT e.entity_id
                        FROM entities e
                        WHERE e.primary_wallet = mt.creator
                          AND e.created_at <= mt.migration_at
                        ORDER BY e.created_at ASC, e.entity_id ASC
                        LIMIT 1
                    ) pe ON ew.entity_id IS NULL
                    WHERE mt.creator IS NOT NULL
                      AND btrim(mt.creator) <> ''
                      AND mt.mint IS NOT NULL
                      AND COALESCE(ew.entity_id, pe.entity_id) IS NOT NULL
                )
                SELECT
                    COUNT(*)::int AS historically_resolvable_migrations,
                    COUNT(*) FILTER (
                        WHERE NOT EXISTS (
                            SELECT 1 FROM entity_launches el WHERE el.mint = resolved.mint
                        )
                    )::int AS unbridged_historically_resolvable_migrations
                FROM resolved
            """))).mappings().first()
            if bridge_row:
                bridge_counts = {
                    "historically_resolvable_migrations": int(bridge_row.get("historically_resolvable_migrations") or 0),
                    "unbridged_historically_resolvable_migrations": int(bridge_row.get("unbridged_historically_resolvable_migrations") or 0),
                }
        except Exception:
            pass

    return {
        "status": "OBSERVED" if not missing_tables else "PARTIAL",
        "tables": table_state,
        "counts": {**counts, **bridge_counts},
        "missing_tables": missing_tables,
        "failure_stage": None,
        "bridge_policy": {
            "source": "migration_tracks",
            "requires_historical_creator_entity_evidence": True,
            "preserve_migration_at_as_observed_at": True,
            "backfill_time_remains_ingestion_time": True,
            "future_entity_inference_forbidden": True,
            "entity_launch_count_aggregate_modified": False,
        },
        "bounded": {"table_count": len(_REQUIRED_TABLES), "count_queries_max": 9},
        **AUTHORITY,
    }


async def recover_historical_research_bridge(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Idempotently bridge only historically defensible migration→entity launch rows."""
    limit = max(1, min(5000, int(limit)))
    preflight = await historical_research_bridge_preflight(session)
    required = ("migration_tracks", "entity_launches", "entities", "entity_wallets")
    if not all((preflight.get("tables") or {}).get(name) for name in required):
        return {
            "status": "BLOCKED",
            "inserted_count": 0,
            "reason": "required_bridge_tables_missing",
            "preflight": preflight,
            "bounded": {"limit": limit},
            **AUTHORITY,
        }

    try:
        rows = (await session.execute(text("""
            WITH candidates AS (
                SELECT
                    mt.track_id::text AS track_id,
                    mt.mint,
                    mt.creator AS deployer_wallet,
                    mt.migration_signature,
                    mt.migration_at,
                    COALESCE(ew.entity_id, pe.entity_id) AS entity_id
                FROM migration_tracks mt
                LEFT JOIN LATERAL (
                    SELECT x.entity_id
                    FROM entity_wallets x
                    WHERE x.wallet = mt.creator
                      AND x.first_seen_at IS NOT NULL
                      AND x.first_seen_at <= mt.migration_at
                    ORDER BY x.first_seen_at ASC, x.id ASC
                    LIMIT 1
                ) ew ON TRUE
                LEFT JOIN LATERAL (
                    SELECT e.entity_id
                    FROM entities e
                    WHERE e.primary_wallet = mt.creator
                      AND e.created_at <= mt.migration_at
                    ORDER BY e.created_at ASC, e.entity_id ASC
                    LIMIT 1
                ) pe ON ew.entity_id IS NULL
                WHERE mt.creator IS NOT NULL
                  AND btrim(mt.creator) <> ''
                  AND mt.mint IS NOT NULL
                  AND btrim(mt.mint) <> ''
                  AND COALESCE(ew.entity_id, pe.entity_id) IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM entity_launches existing WHERE existing.mint = mt.mint
                  )
                ORDER BY mt.migration_at ASC, mt.track_id ASC
                LIMIT :limit
            )
            INSERT INTO entity_launches (
                entity_id, deployer_wallet, mint, event_id, observed_at
            )
            SELECT
                entity_id,
                deployer_wallet,
                mint,
                'migration_bridge:' || COALESCE(NULLIF(migration_signature, ''), track_id),
                migration_at
            FROM candidates
            ON CONFLICT DO NOTHING
            RETURNING id, mint, entity_id::text AS entity_id, deployer_wallet, event_id, observed_at, created_at
        """), {"limit": limit})).mappings().all()
        await session.commit()
    except Exception as exc:
        await session.rollback()
        return {
            "status": "UNAVAILABLE",
            "inserted_count": 0,
            "reason": "bridge_insert_failed",
            "error_type": type(exc).__name__,
            "preflight": preflight,
            "bounded": {"limit": limit},
            **AUTHORITY,
        }

    records = []
    for row in rows:
        item = dict(row)
        for key in ("observed_at", "created_at"):
            if item.get(key) is not None and hasattr(item[key], "isoformat"):
                item[key] = item[key].isoformat()
        records.append(item)
    after = await historical_research_bridge_preflight(session)
    return {
        "status": "RECOVERED" if records else "NO_CHANGE",
        "inserted_count": len(records),
        "records": records[:100],
        "records_truncated": len(records) > 100,
        "preflight_before": preflight,
        "preflight_after": after,
        "historical_timestamp_preserved": True,
        "future_entity_inference_forbidden": True,
        "entity_launch_count_aggregate_modified": False,
        "bounded": {"limit": limit, "returned_records": min(len(records), 100)},
        **AUTHORITY,
    }
