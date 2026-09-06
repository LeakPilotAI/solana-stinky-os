"""Read-only completeness audit for prospective Phase-10 research evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "PROSPECTIVE_PHASE10_CORPUS_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


async def audit_prospective_phase10_corpus(
    session: AsyncSession,
    *,
    limit: int = 200,
    feature_horizon_seconds: int = 300,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Measure migration-anchored evidence completeness without changing research gates.

    The prospective cohort is identified by immutable ``token.migrated`` events,
    not by ``entity_launches.event_id``. A token may already have an entity-launch
    row from ``token.launch`` and ``entity_launches`` intentionally enforces one
    row per ``(deployer_wallet, mint)``. Duplicate migration events for the same
    mint are collapsed to the earliest dual-time-visible migration observation.
    """
    limit = max(1, min(500, int(limit)))
    feature_horizon_seconds = max(0, min(1800, int(feature_horizon_seconds)))
    cutoff = _parse(as_of) or datetime.now(timezone.utc)
    if as_of is not None and _parse(as_of) is None:
        return {"status": "UNKNOWN", "missing": ["valid_as_of"], **AUTHORITY}

    try:
        preflight = (await session.execute(text("""
            SELECT
              to_regclass('events')::text AS events,
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('developer_longitudinal_snapshots')::text AS developer_longitudinal_snapshots,
              to_regclass('developer_correlation_snapshots')::text AS developer_correlation_snapshots,
              to_regclass('market_outcome_observations')::text AS market_outcome_observations
        """))).mappings().first()
    except Exception as exc:
        return {"status": "UNKNOWN", "failure_stage": "table_preflight", "error_type": type(exc).__name__, **AUTHORITY}

    table_names = (
        "events",
        "entity_launches",
        "developer_longitudinal_snapshots",
        "developer_correlation_snapshots",
        "market_outcome_observations",
    )
    tables = {name: bool(preflight and preflight.get(name)) for name in table_names}
    missing = [name for name, present in tables.items() if not present]
    if missing:
        return {"status": "BLOCKED", "tables": tables, "missing": missing, **AUTHORITY}

    params = {
        "limit": limit,
        "dataset_as_of": cutoff,
        "feature_seconds": feature_horizon_seconds,
    }
    try:
        cohort = (await session.execute(text("""
            WITH canonical_migrations AS (
                SELECT DISTINCT ON (e.payload->>'mint')
                       e.payload->>'mint' AS mint,
                       COALESCE(e.payload->>'creator', e.payload->>'deployer') AS creator,
                       e.event_id::text AS migration_event_id,
                       e.occurred_at AS migration_observed_at,
                       e.ingested_at AS migration_ingested_at
                FROM events e
                WHERE e.event_type = 'token.migrated'
                  AND e.payload->>'mint' IS NOT NULL
                  AND e.occurred_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
                  AND e.ingested_at <= :dataset_as_of
                  AND e.ingested_at <= e.occurred_at + make_interval(secs => :feature_seconds)
                ORDER BY e.payload->>'mint', e.occurred_at ASC, e.ingested_at ASC, e.event_id ASC
            )
            SELECT m.mint, m.creator,
                   m.migration_event_id,
                   m.migration_observed_at,
                   m.migration_ingested_at,
                   m.migration_observed_at + make_interval(secs => :feature_seconds) AS feature_as_of,
                   l.id AS launch_id,
                   l.entity_id::text AS entity_id,
                   l.deployer_wallet,
                   l.event_id AS launch_event_id,
                   l.observed_at AS launch_observed_at,
                   l.created_at AS launch_ingested_at
            FROM canonical_migrations m
            LEFT JOIN entity_launches l
              ON l.mint = m.mint
             AND m.creator IS NOT NULL
             AND l.deployer_wallet = m.creator
            ORDER BY m.migration_observed_at DESC, m.mint
            LIMIT :limit
        """), params)).mappings().all()
    except Exception as exc:
        return {"status": "UNKNOWN", "tables": tables, "failure_stage": "cohort_query", "error_type": type(exc).__name__, **AUTHORITY}

    rows = [dict(row) for row in cohort]
    if not rows:
        return {
            "status": "NO_PROSPECTIVE_ROWS",
            "tables": tables,
            "row_count": 0,
            "feature_complete_count": 0,
            "feature_complete_coverage": None,
            "rows": [],
            "bounded": {"limit": limit, "query_count_max": 5},
            "prospective_policy": {
                "historical_reconstruction": False,
                "cohort_basis": "immutable token.migrated events",
                "migration_events_deduplicated_by": "mint",
                "migration_anchor": "earliest dual-time-visible token.migrated event per mint",
                "entity_launch_event_id_required": False,
                "dual_time_required": True,
                "missing_evidence_remains_unknown": True,
            },
            **AUTHORITY,
        }

    entity_ids = sorted({str(r["entity_id"]) for r in rows if r.get("entity_id")})
    mints = sorted({str(r["mint"]) for r in rows if r.get("mint")})

    developer_by_entity: dict[str, list[dict[str, Any]]] = {}
    correlation_by_entity: dict[str, list[dict[str, Any]]] = {}
    lifecycle_by_mint: dict[str, list[dict[str, Any]]] = {}

    if entity_ids:
        try:
            developer = (await session.execute(text("""
                SELECT entity_id::text AS entity_id, observed_at, ingested_at, evidence_hash
                FROM developer_longitudinal_snapshots
                WHERE entity_id::text = ANY(:entity_ids)
                  AND observed_at <= :dataset_as_of AND ingested_at <= :dataset_as_of
                ORDER BY entity_id, observed_at DESC, id DESC
            """), {"entity_ids": entity_ids, "dataset_as_of": cutoff})).mappings().all()
            for row in developer:
                developer_by_entity.setdefault(str(row["entity_id"]), []).append(dict(row))
        except Exception:
            developer_by_entity = {}

        try:
            correlation = (await session.execute(text("""
                SELECT entity_id::text AS entity_id, observed_at, ingested_at, evidence_hash
                FROM developer_correlation_snapshots
                WHERE entity_id::text = ANY(:entity_ids)
                  AND observed_at <= :dataset_as_of AND ingested_at <= :dataset_as_of
                ORDER BY entity_id, observed_at DESC, id DESC
            """), {"entity_ids": entity_ids, "dataset_as_of": cutoff})).mappings().all()
            for row in correlation:
                correlation_by_entity.setdefault(str(row["entity_id"]), []).append(dict(row))
        except Exception:
            correlation_by_entity = {}

    if mints:
        try:
            lifecycle = (await session.execute(text("""
                SELECT mint, horizon, observed_at, ingested_at, source, evidence_basis
                FROM market_outcome_observations
                WHERE mint = ANY(:mints)
                  AND observed_at <= :dataset_as_of AND ingested_at <= :dataset_as_of
                ORDER BY mint, observed_at DESC, id DESC
            """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
            for row in lifecycle:
                lifecycle_by_mint.setdefault(str(row["mint"]), []).append(dict(row))
        except Exception:
            lifecycle_by_mint = {}

    output_rows: list[dict[str, Any]] = []
    developer_count = correlation_count = lifecycle_count = complete_count = 0
    entity_resolved_count = 0
    for migration in rows:
        feature_as_of = migration["feature_as_of"]
        entity_id = str(migration.get("entity_id") or "")
        mint = str(migration.get("mint") or "")

        dev = next((r for r in developer_by_entity.get(entity_id, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)
        corr = next((r for r in correlation_by_entity.get(entity_id, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)
        life = next((r for r in lifecycle_by_mint.get(mint, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)

        entity_resolved = bool(entity_id)
        has_dev = dev is not None
        has_corr = corr is not None
        has_life = life is not None
        complete = has_dev and has_corr and has_life
        entity_resolved_count += int(entity_resolved)
        developer_count += int(has_dev)
        correlation_count += int(has_corr)
        lifecycle_count += int(has_life)
        complete_count += int(complete)

        output_rows.append({
            "mint": mint,
            "creator": migration.get("creator"),
            "entity_id": entity_id or None,
            "entity_resolved": entity_resolved,
            "migration_event_id": migration.get("migration_event_id"),
            "migration_observed_at": _iso(migration.get("migration_observed_at")),
            "migration_ingested_at": _iso(migration.get("migration_ingested_at")),
            "launch_event_id": migration.get("launch_event_id"),
            "feature_as_of": _iso(feature_as_of),
            "developer_dual_time_visible": has_dev,
            "correlation_dual_time_visible": has_corr,
            "lifecycle_dual_time_visible": has_life,
            "feature_complete": complete,
            "lifecycle_evidence_basis": life.get("evidence_basis") if life else None,
        })

    total = len(output_rows)
    return {
        "status": "OBSERVED",
        "tables": tables,
        "row_count": total,
        "entity_resolved_count": entity_resolved_count,
        "entity_resolved_coverage": entity_resolved_count / total,
        "developer_dual_time_count": developer_count,
        "developer_dual_time_coverage": developer_count / total,
        "correlation_dual_time_count": correlation_count,
        "correlation_dual_time_coverage": correlation_count / total,
        "lifecycle_dual_time_count": lifecycle_count,
        "lifecycle_dual_time_coverage": lifecycle_count / total,
        "feature_complete_count": complete_count,
        "feature_complete_coverage": complete_count / total,
        "rows": output_rows,
        "bounded": {"limit": limit, "feature_horizon_seconds": feature_horizon_seconds, "query_count_max": 5},
        "prospective_policy": {
            "historical_reconstruction": False,
            "cohort_basis": "immutable token.migrated events",
            "migration_events_deduplicated_by": "mint",
            "migration_anchor": "earliest dual-time-visible token.migrated event per mint",
            "entity_launch_event_id_required": False,
            "dual_time_required": True,
            "missing_evidence_remains_unknown": True,
        },
        **AUTHORITY,
    }
