"""Conservative historical evidence reconstruction for Phase-10 research.

Historical migration rows may be promoted into canonical launch memory only from
measured migration facts already present in Postgres. Derived developer/correlation
snapshots are never backdated. Their ingestion timestamps remain authoritative.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.developer_correlation_audit import ensure_developer_correlation_audit_table
from stinky_api.developer_longitudinal_audit import ensure_developer_audit_table

AUTHORITY = {
    "interpretation": "HISTORICAL_EVIDENCE_RECONSTRUCTION_ONLY",
    "historical_developer_snapshot_reconstruction_authorized": False,
    "historical_correlation_snapshot_reconstruction_authorized": False,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}

_REQUIRED = ("migration_tracks", "entity_launches", "entities", "entity_wallets", "events")


async def historical_reconstruction_audit(
    session: AsyncSession,
    *,
    feature_horizon_seconds: int = 300,
) -> dict[str, Any]:
    """Measure what can be reconstructed without inventing past feature knowledge."""
    feature_horizon_seconds = max(0, min(1800, int(feature_horizon_seconds)))
    try:
        tables = (await session.execute(text("""
            SELECT
              to_regclass('migration_tracks')::text AS migration_tracks,
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('entities')::text AS entities,
              to_regclass('entity_wallets')::text AS entity_wallets,
              to_regclass('events')::text AS events,
              to_regclass('market_outcome_observations')::text AS market_outcome_observations,
              to_regclass('developer_longitudinal_snapshots')::text AS developer_longitudinal_snapshots,
              to_regclass('developer_correlation_snapshots')::text AS developer_correlation_snapshots
        """))).mappings().first()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "failure_stage": "table_preflight",
            "error_type": type(exc).__name__,
            "tables": {},
            "counts": {},
            **AUTHORITY,
        }

    table_state = {key: bool(tables and tables.get(key)) for key in (
        *_REQUIRED,
        "market_outcome_observations",
        "developer_longitudinal_snapshots",
        "developer_correlation_snapshots",
    )}
    missing_required = [name for name in _REQUIRED if not table_state.get(name)]
    if missing_required:
        return {
            "status": "BLOCKED",
            "failure_stage": "required_tables_missing",
            "tables": table_state,
            "missing_required_tables": missing_required,
            "counts": {},
            **AUTHORITY,
        }

    params = {"feature_seconds": feature_horizon_seconds}
    try:
        row = (await session.execute(text("""
            WITH migrations AS (
                SELECT mt.track_id, mt.mint, mt.creator, mt.migration_at,
                       mt.migration_signature,
                       mt.migration_at + make_interval(secs => :feature_seconds) AS feature_as_of
                FROM migration_tracks mt
            ), identity_evidence AS (
                SELECT m.mint,
                       EXISTS (
                           SELECT 1 FROM events e
                           WHERE e.event_type IN ('token.migrated', 'token.launch')
                             AND e.payload->>'mint' = m.mint
                             AND COALESCE(e.payload->>'creator', e.payload->>'deployer') = m.creator
                             AND e.occurred_at <= m.feature_as_of
                             AND e.ingested_at <= m.feature_as_of
                       ) AS known_by_feature_cutoff
                FROM migrations m
                WHERE m.mint IS NOT NULL AND m.creator IS NOT NULL AND btrim(m.creator) <> ''
            ), labels AS (
                SELECT DISTINCT e.payload->>'mint' AS mint
                FROM events e
                WHERE e.event_type = 'post_migration.tracking_completed'
                  AND e.payload->>'mint' IS NOT NULL
            )
            SELECT
                COUNT(*)::int AS migration_count,
                COUNT(*) FILTER (WHERE m.creator IS NOT NULL AND btrim(m.creator) <> '')::int AS creator_observed_count,
                COUNT(*) FILTER (WHERE m.creator IS NOT NULL AND btrim(m.creator) <> '' AND m.mint IS NOT NULL)::int AS direct_launch_identity_reconstructable_count,
                COUNT(*) FILTER (WHERE l.id IS NOT NULL)::int AS entity_launch_count,
                COUNT(*) FILTER (WHERE m.creator IS NOT NULL AND btrim(m.creator) <> '' AND m.mint IS NOT NULL AND l.id IS NULL)::int AS direct_launch_identity_unbridged_count,
                COUNT(*) FILTER (WHERE ie.known_by_feature_cutoff)::int AS immutable_identity_event_known_by_feature_cutoff_count,
                COUNT(*) FILTER (WHERE lbl.mint IS NOT NULL)::int AS completion_label_mint_count
            FROM migrations m
            LEFT JOIN entity_launches l ON l.mint = m.mint
            LEFT JOIN identity_evidence ie ON ie.mint = m.mint
            LEFT JOIN labels lbl ON lbl.mint = m.mint
        """), params)).mappings().first()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "failure_stage": "historical_inventory",
            "error_type": type(exc).__name__,
            "tables": table_state,
            "counts": {},
            **AUTHORITY,
        }

    counts = {key: int((row or {}).get(key) or 0) for key in (
        "migration_count",
        "creator_observed_count",
        "direct_launch_identity_reconstructable_count",
        "entity_launch_count",
        "direct_launch_identity_unbridged_count",
        "immutable_identity_event_known_by_feature_cutoff_count",
        "completion_label_mint_count",
    )}

    if table_state.get("market_outcome_observations"):
        try:
            lifecycle = (await session.execute(text("""
                SELECT COUNT(DISTINCT mt.mint)::int
                FROM migration_tracks mt
                JOIN market_outcome_observations o ON o.mint = mt.mint
                WHERE o.observed_at <= mt.migration_at + make_interval(secs => :feature_seconds)
                  AND o.ingested_at <= mt.migration_at + make_interval(secs => :feature_seconds)
            """), params)).scalar()
            counts["lifecycle_mints_known_by_feature_cutoff_count"] = int(lifecycle or 0)
        except Exception:
            counts["lifecycle_mints_known_by_feature_cutoff_count"] = 0
    else:
        counts["lifecycle_mints_known_by_feature_cutoff_count"] = 0

    for table_name in ("developer_longitudinal_snapshots", "developer_correlation_snapshots"):
        if table_state.get(table_name):
            try:
                value = (await session.execute(text(f"SELECT COUNT(*)::int FROM {table_name}"))).scalar()
                counts[table_name] = int(value or 0)
            except Exception:
                counts[table_name] = 0
        else:
            counts[table_name] = 0

    denominator = counts["direct_launch_identity_reconstructable_count"]
    counts["completion_label_coverage_if_launches_recovered"] = (
        counts["completion_label_mint_count"] / denominator if denominator else None
    )
    counts["immutable_identity_event_coverage_at_feature_cutoff"] = (
        counts["immutable_identity_event_known_by_feature_cutoff_count"] / denominator if denominator else None
    )
    counts["lifecycle_feature_coverage_at_feature_cutoff"] = (
        counts["lifecycle_mints_known_by_feature_cutoff_count"] / denominator if denominator else None
    )

    return {
        "status": "OBSERVED",
        "tables": table_state,
        "counts": counts,
        "feature_horizon_seconds": feature_horizon_seconds,
        "historical_policy": {
            "direct_migration_creator_is_factual_launch_identity": True,
            "recovered_launch_observed_at_uses_migration_at": True,
            "recovered_launch_ingested_at_remains_recovery_time": True,
            "derived_snapshots_are_not_backdated": True,
            "future_entity_graph_inference_forbidden_for_historical_features": True,
            "raw_event_feature_cutoff_requires_occurred_and_ingested_time": True,
        },
        "next_action": (
            "RECOVER_DIRECT_LAUNCH_IDENTITIES"
            if counts["direct_launch_identity_unbridged_count"] > 0
            else "COLLECT_OR_CAPTURE_FEATURE_EVIDENCE"
        ),
        **AUTHORITY,
    }


async def initialize_phase10_snapshot_memory(session: AsyncSession) -> dict[str, Any]:
    """Create empty snapshot memory prospectively; never fabricate historical rows."""
    try:
        await ensure_developer_audit_table(session)
        await ensure_developer_correlation_audit_table(session)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        return {"status": "UNAVAILABLE", "error_type": type(exc).__name__, **AUTHORITY}
    return {
        "status": "INITIALIZED",
        "developer_longitudinal_snapshots_created_if_missing": True,
        "developer_correlation_snapshots_created_if_missing": True,
        "historical_rows_inserted": 0,
        **AUTHORITY,
    }


async def recover_direct_migration_launches(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Recover launch identity from migration_tracks without backdating derived evidence."""
    limit = max(1, min(5000, int(limit)))
    audit_before = await historical_reconstruction_audit(session)
    if audit_before.get("status") != "OBSERVED":
        return {"status": "BLOCKED", "inserted_count": 0, "audit_before": audit_before, **AUTHORITY}

    try:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('phase10-historical-evidence-reconstruction'))"))
        candidates = (await session.execute(text("""
            SELECT mt.track_id::text AS track_id, mt.mint, mt.creator,
                   mt.migration_at, mt.migration_signature
            FROM migration_tracks mt
            WHERE mt.mint IS NOT NULL AND btrim(mt.mint) <> ''
              AND mt.creator IS NOT NULL AND btrim(mt.creator) <> ''
              AND NOT EXISTS (SELECT 1 FROM entity_launches l WHERE l.mint = mt.mint)
            ORDER BY mt.migration_at ASC, mt.track_id ASC
            LIMIT :limit
        """), {"limit": limit})).mappings().all()

        inserted: list[dict[str, Any]] = []
        for candidate in candidates:
            creator = str(candidate.get("creator") or "").strip()
            mint = str(candidate.get("mint") or "").strip()
            migration_at = candidate.get("migration_at")
            if not creator or not mint or migration_at is None:
                continue

            entity_row = (await session.execute(text("""
                SELECT e.entity_id
                FROM entities e
                LEFT JOIN entity_wallets ew ON ew.entity_id = e.entity_id AND ew.wallet = :wallet
                WHERE ew.wallet = :wallet OR e.primary_wallet = :wallet
                ORDER BY CASE WHEN ew.wallet IS NOT NULL THEN 0 ELSE 1 END, e.created_at ASC
                LIMIT 1
            """), {"wallet": creator})).first()

            if entity_row:
                entity_id = entity_row[0]
            else:
                entity_id = (await session.execute(text("""
                    INSERT INTO entities (
                        entity_type, display_label, primary_wallet,
                        wallet_count, launch_count, early_buy_count, confidence, meta
                    ) VALUES (
                        'deployer', :label, :wallet,
                        0, 0, 0, 1.0, CAST(:meta AS jsonb)
                    ) RETURNING entity_id
                """), {
                    "label": f"dep:{creator[:6]}",
                    "wallet": creator,
                    "meta": json.dumps({
                        "evidence_basis": "migration_tracks.creator",
                        "identity_interpretation": "exact_observed_creator_wallet",
                        "historical_reconstruction": True,
                    }, sort_keys=True),
                })).scalar_one()

            wallet_evidence = json.dumps({
                "evidence_basis": "migration_tracks.creator",
                "mint": mint,
                "track_id": str(candidate.get("track_id") or ""),
                "observed_at": migration_at.isoformat() if hasattr(migration_at, "isoformat") else str(migration_at),
                "ownership_inferred": False,
                "identity_inferred": False,
            }, sort_keys=True)
            await session.execute(text("""
                INSERT INTO entity_wallets (
                    entity_id, wallet, role, link_reason, confidence,
                    first_seen_at, last_seen_at, evidence
                ) VALUES (
                    :entity_id, :wallet, 'primary', 'migration_creator_observed', 1.0,
                    :observed_at, :observed_at, CAST(:evidence AS jsonb)
                )
                ON CONFLICT (wallet) DO UPDATE SET
                    first_seen_at = LEAST(COALESCE(entity_wallets.first_seen_at, EXCLUDED.first_seen_at), EXCLUDED.first_seen_at),
                    last_seen_at = GREATEST(COALESCE(entity_wallets.last_seen_at, EXCLUDED.last_seen_at), EXCLUDED.last_seen_at),
                    evidence = COALESCE(entity_wallets.evidence, '{}'::jsonb) || EXCLUDED.evidence
            """), {
                "entity_id": entity_id,
                "wallet": creator,
                "observed_at": migration_at,
                "evidence": wallet_evidence,
            })

            event_identity = str(candidate.get("migration_signature") or "").strip() or str(candidate.get("track_id") or "")
            row = (await session.execute(text("""
                INSERT INTO entity_launches (
                    entity_id, deployer_wallet, mint, event_id, observed_at
                ) VALUES (
                    :entity_id, :wallet, :mint, :event_id, :observed_at
                )
                ON CONFLICT DO NOTHING
                RETURNING id, created_at
            """), {
                "entity_id": entity_id,
                "wallet": creator,
                "mint": mint,
                "event_id": f"migration_reconstruction:{event_identity}",
                "observed_at": migration_at,
            })).first()
            if row:
                inserted.append({
                    "mint": mint,
                    "deployer_wallet": creator,
                    "entity_id": str(entity_id),
                    "observed_at": migration_at.isoformat() if hasattr(migration_at, "isoformat") else str(migration_at),
                    "ingested_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                })

        await session.commit()
    except Exception as exc:
        await session.rollback()
        return {
            "status": "UNAVAILABLE",
            "inserted_count": 0,
            "error_type": type(exc).__name__,
            "audit_before": audit_before,
            **AUTHORITY,
        }

    audit_after = await historical_reconstruction_audit(session)
    return {
        "status": "RECOVERED" if inserted else "NO_CHANGE",
        "inserted_count": len(inserted),
        "records": inserted[:100],
        "records_truncated": len(inserted) > 100,
        "audit_before": audit_before,
        "audit_after": audit_after,
        "entity_launch_count_aggregate_modified": False,
        "historical_snapshots_backdated": False,
        "bounded": {"limit": limit, "returned_records": min(len(inserted), 100)},
        **AUTHORITY,
    }
