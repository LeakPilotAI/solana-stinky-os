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
    """Measure future-only evidence completeness without changing research gates."""
    limit = max(1, min(500, int(limit)))
    feature_horizon_seconds = max(0, min(1800, int(feature_horizon_seconds)))
    cutoff = _parse(as_of) or datetime.now(timezone.utc)
    if as_of is not None and _parse(as_of) is None:
        return {"status": "UNKNOWN", "missing": ["valid_as_of"], **AUTHORITY}

    try:
        preflight = (await session.execute(text("""
            SELECT
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('developer_longitudinal_snapshots')::text AS developer_longitudinal_snapshots,
              to_regclass('developer_correlation_snapshots')::text AS developer_correlation_snapshots,
              to_regclass('market_outcome_observations')::text AS market_outcome_observations
        """))).mappings().first()
    except Exception as exc:
        return {"status": "UNKNOWN", "failure_stage": "table_preflight", "error_type": type(exc).__name__, **AUTHORITY}

    table_names = (
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
            SELECT l.id AS launch_id, l.entity_id::text AS entity_id, l.mint,
                   l.deployer_wallet, l.event_id,
                   l.observed_at AS launch_observed_at,
                   l.created_at AS launch_ingested_at,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of
            FROM entity_launches l
            WHERE l.mint IS NOT NULL
              AND l.event_id LIKE 'migrated:%'
              AND l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
              AND l.created_at <= :dataset_as_of
            ORDER BY l.observed_at DESC, l.id DESC
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
            "bounded": {"limit": limit, "query_count_max": 4},
            **AUTHORITY,
        }

    entity_ids = sorted({str(r["entity_id"]) for r in rows if r.get("entity_id")})
    mints = sorted({str(r["mint"]) for r in rows if r.get("mint")})

    developer_by_entity: dict[str, list[dict[str, Any]]] = {}
    correlation_by_entity: dict[str, list[dict[str, Any]]] = {}
    lifecycle_by_mint: dict[str, list[dict[str, Any]]] = {}

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
    for launch in rows:
        feature_as_of = launch["feature_as_of"]
        entity_id = str(launch.get("entity_id") or "")
        mint = str(launch.get("mint") or "")

        dev = next((r for r in developer_by_entity.get(entity_id, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)
        corr = next((r for r in correlation_by_entity.get(entity_id, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)
        life = next((r for r in lifecycle_by_mint.get(mint, []) if r.get("observed_at") <= feature_as_of and r.get("ingested_at") <= feature_as_of), None)

        has_dev = dev is not None
        has_corr = corr is not None
        has_life = life is not None
        complete = has_dev and has_corr and has_life
        developer_count += int(has_dev)
        correlation_count += int(has_corr)
        lifecycle_count += int(has_life)
        complete_count += int(complete)

        output_rows.append({
            "mint": mint,
            "entity_id": entity_id,
            "launch_observed_at": _iso(launch.get("launch_observed_at")),
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
        "developer_dual_time_count": developer_count,
        "developer_dual_time_coverage": developer_count / total,
        "correlation_dual_time_count": correlation_count,
        "correlation_dual_time_coverage": correlation_count / total,
        "lifecycle_dual_time_count": lifecycle_count,
        "lifecycle_dual_time_coverage": lifecycle_count / total,
        "feature_complete_count": complete_count,
        "feature_complete_coverage": complete_count / total,
        "rows": output_rows,
        "bounded": {"limit": limit, "feature_horizon_seconds": feature_horizon_seconds, "query_count_max": 4},
        "prospective_policy": {
            "historical_reconstruction": False,
            "prospective_launch_identity": "entity_launches.event_id LIKE migrated:%",
            "dual_time_required": True,
            "missing_evidence_remains_unknown": True,
        },
        **AUTHORITY,
    }
