"""Exact-cohort provenance audit for Phase-10 research evidence.

The audit mirrors ``pattern_discovery_dataset`` candidate ordering, explains label
attribution, and inventories historical feature evidence without backdating or
inventing timestamps that were never stored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CANONICAL_OUTCOMES = {"RUNNER", "HELD", "FADE", "UNKNOWN"}
AUTHORITY = {
    "interpretation": "PHASE10_COHORT_PROVENANCE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def canonical_token_outcome_label(value: Any) -> str:
    """Map only semantically defensible legacy measured labels.

    ``mega_runner`` and ``runner`` both satisfy explicit legacy runner rules.
    ``fade`` is explicitly fade. ``mid`` is not equivalent to HELD and remains
    UNKNOWN rather than being silently reinterpreted.
    """
    raw = str(value or "").strip().lower()
    if raw in {"mega_runner", "runner"}:
        return "RUNNER"
    if raw == "fade":
        return "FADE"
    return "UNKNOWN"


def canonical_completion_event_label(payload: Any) -> str:
    """Use completion events as labels only when they explicitly carry one."""
    if not isinstance(payload, dict):
        return "UNKNOWN"
    raw = str(
        payload.get("outcome_status")
        or payload.get("outcome")
        or payload.get("status")
        or "UNKNOWN"
    ).upper()
    return raw if raw in CANONICAL_OUTCOMES else "UNKNOWN"


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


async def audit_phase10_cohort_provenance(
    session: AsyncSession,
    *,
    limit: int = 200,
    feature_horizon_seconds: int = 300,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Audit the exact bounded launch cohort used by Phase-10 dataset formation.

    Query count is bounded independently of cohort size: table preflight, cohort,
    completion events, optional token outcomes, and one bulk feature-visibility
    query. The diagnostic never persists or repairs evidence.
    """
    limit = max(1, min(500, int(limit)))
    feature_horizon_seconds = max(0, min(1800, int(feature_horizon_seconds)))
    cutoff = _parse(as_of) or datetime.now(timezone.utc)
    if as_of is not None and _parse(as_of) is None:
        return {"status": "UNKNOWN", "missing": ["valid_as_of"], **AUTHORITY}

    try:
        table_row = (await session.execute(text("""
            SELECT
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('events')::text AS events,
              to_regclass('token_outcomes')::text AS token_outcomes,
              to_regclass('market_snapshots')::text AS market_snapshots,
              to_regclass('market_outcome_observations')::text AS market_outcome_observations,
              to_regclass('developer_longitudinal_snapshots')::text AS developer_longitudinal_snapshots,
              to_regclass('developer_correlation_snapshots')::text AS developer_correlation_snapshots
        """))).mappings().first()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "failure_stage": "table_preflight",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    names = (
        "entity_launches",
        "events",
        "token_outcomes",
        "market_snapshots",
        "market_outcome_observations",
        "developer_longitudinal_snapshots",
        "developer_correlation_snapshots",
    )
    tables = {name: bool(table_row and table_row.get(name)) for name in names}
    required_missing = [name for name in ("entity_launches", "events") if not tables[name]]
    if required_missing:
        return {
            "status": "BLOCKED",
            "tables": tables,
            "missing": required_missing,
            **AUTHORITY,
        }

    params = {
        "limit": limit,
        "dataset_as_of": cutoff,
        "feature_seconds": feature_horizon_seconds,
    }
    try:
        cohort = (await session.execute(text("""
            SELECT l.id AS launch_id, l.entity_id::text AS entity_id, l.mint,
                   l.observed_at AS launch_observed_at,
                   l.created_at AS launch_ingested_at,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of
            FROM entity_launches l
            WHERE l.mint IS NOT NULL
              AND l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
              AND l.created_at <= :dataset_as_of
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :limit
        """), params)).mappings().all()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "tables": tables,
            "failure_stage": "cohort_query",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    rows = [dict(row) for row in cohort]
    mints = [str(row["mint"]) for row in rows if row.get("mint")]
    if not mints:
        return {
            "status": "UNKNOWN",
            "tables": tables,
            "row_count": 0,
            "reason_counts": {},
            "rows": [],
            "bounded": {"limit": limit, "query_count_max": 5},
            **AUTHORITY,
        }

    completion_by_mint: dict[str, dict[str, Any]] = {}
    try:
        completion_rows = (await session.execute(text("""
            SELECT DISTINCT ON (e.payload->>'mint')
                   e.payload->>'mint' AS mint,
                   e.event_id::text AS event_id,
                   e.occurred_at,
                   e.ingested_at,
                   e.payload
            FROM events e
            WHERE e.event_type = 'post_migration.tracking_completed'
              AND e.payload->>'mint' = ANY(:mints)
              AND e.occurred_at <= :dataset_as_of
              AND e.ingested_at <= :dataset_as_of
            ORDER BY e.payload->>'mint', e.occurred_at DESC, e.ingested_at DESC
        """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
        completion_by_mint = {
            str(row["mint"]): dict(row) for row in completion_rows if row.get("mint")
        }
    except Exception:
        completion_by_mint = {}

    outcome_by_mint: dict[str, dict[str, Any]] = {}
    if tables["token_outcomes"]:
        try:
            outcome_rows = (await session.execute(text("""
                SELECT mint, label, evaluated_at, migration_at, snapshots_n,
                       peak_volume_m5_usd, peak_liquidity_usd,
                       peak_market_cap_usd, peak_price_usd, notes
                FROM token_outcomes
                WHERE mint = ANY(:mints)
                  AND evaluated_at <= :dataset_as_of
            """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
            outcome_by_mint = {
                str(row["mint"]): dict(row) for row in outcome_rows if row.get("mint")
            }
        except Exception:
            outcome_by_mint = {}

    feature_selects = ["c.mint"]
    feature_selects.append(
        "EXISTS (SELECT 1 FROM developer_longitudinal_snapshots s "
        "WHERE s.entity_id = c.entity_id AND s.observed_at <= c.feature_as_of "
        "AND s.ingested_at <= c.feature_as_of) AS developer_dual_time_visible"
        if tables["developer_longitudinal_snapshots"]
        else "FALSE AS developer_dual_time_visible"
    )
    feature_selects.append(
        "EXISTS (SELECT 1 FROM developer_correlation_snapshots s "
        "WHERE s.entity_id = c.entity_id AND s.observed_at <= c.feature_as_of "
        "AND s.ingested_at <= c.feature_as_of) AS correlation_dual_time_visible"
        if tables["developer_correlation_snapshots"]
        else "FALSE AS correlation_dual_time_visible"
    )
    feature_selects.append(
        "EXISTS (SELECT 1 FROM market_outcome_observations o "
        "WHERE o.mint = c.mint AND o.observed_at <= c.feature_as_of "
        "AND o.ingested_at <= c.feature_as_of) AS lifecycle_dual_time_visible"
        if tables["market_outcome_observations"]
        else "FALSE AS lifecycle_dual_time_visible"
    )
    feature_selects.append(
        "EXISTS (SELECT 1 FROM market_snapshots ms "
        "WHERE ms.mint = c.mint AND ms.captured_at <= c.feature_as_of) "
        "AS market_snapshot_captured_by_cutoff"
        if tables["market_snapshots"]
        else "FALSE AS market_snapshot_captured_by_cutoff"
    )
    feature_sql = """
        WITH c AS (
            SELECT l.entity_id, l.mint,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of
            FROM entity_launches l
            WHERE l.mint IS NOT NULL
              AND l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
              AND l.created_at <= :dataset_as_of
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :limit
        )
        SELECT """ + ", ".join(feature_selects) + " FROM c"
    feature_by_mint: dict[str, dict[str, Any]] = {}
    try:
        feature_rows = (await session.execute(text(feature_sql), params)).mappings().all()
        feature_by_mint = {
            str(row["mint"]): dict(row) for row in feature_rows if row.get("mint")
        }
    except Exception:
        feature_by_mint = {}

    feature_keys = (
        "developer_dual_time_visible",
        "correlation_dual_time_visible",
        "lifecycle_dual_time_visible",
        "market_snapshot_captured_by_cutoff",
    )
    feature_counts = {key: 0 for key in feature_keys}
    reason_counts: dict[str, int] = {}
    output_rows: list[dict[str, Any]] = []

    for launch in rows:
        mint = str(launch.get("mint") or "")
        completion = completion_by_mint.get(mint)
        token_outcome = outcome_by_mint.get(mint)
        event_label = canonical_completion_event_label((completion or {}).get("payload"))
        legacy_label = canonical_token_outcome_label((token_outcome or {}).get("label"))
        if event_label != "UNKNOWN":
            resolved_label = event_label
            label_basis = "explicit_tracking_completed_outcome"
        elif legacy_label != "UNKNOWN":
            resolved_label = legacy_label
            label_basis = "measured_token_outcomes_safe_mapping"
        elif token_outcome is not None:
            resolved_label = "UNKNOWN"
            label_basis = "token_outcome_not_semantically_canonical"
        elif completion is not None:
            resolved_label = "UNKNOWN"
            label_basis = "tracking_completed_has_no_canonical_outcome"
        else:
            resolved_label = "UNKNOWN"
            label_basis = "no_label_evidence"
        reason_counts[label_basis] = reason_counts.get(label_basis, 0) + 1

        feature = feature_by_mint.get(mint, {})
        for key in feature_keys:
            feature_counts[key] += int(bool(feature.get(key)))

        output_rows.append({
            "mint": mint,
            "entity_id": launch.get("entity_id"),
            "launch_observed_at": _iso(launch.get("launch_observed_at")),
            "launch_ingested_at": _iso(launch.get("launch_ingested_at")),
            "feature_as_of": _iso(launch.get("feature_as_of")),
            "completion_event_present": completion is not None,
            "completion_event_has_explicit_canonical_outcome": event_label != "UNKNOWN",
            "completion_event_observed_at": _iso((completion or {}).get("occurred_at")),
            "completion_event_ingested_at": _iso((completion or {}).get("ingested_at")),
            "token_outcome_present": token_outcome is not None,
            "token_outcome_raw_label": (token_outcome or {}).get("label"),
            "token_outcome_evaluated_at": _iso((token_outcome or {}).get("evaluated_at")),
            "resolved_label": resolved_label,
            "label_basis": label_basis,
            "developer_dual_time_visible": bool(feature.get("developer_dual_time_visible")),
            "correlation_dual_time_visible": bool(feature.get("correlation_dual_time_visible")),
            "lifecycle_dual_time_visible": bool(feature.get("lifecycle_dual_time_visible")),
            "market_snapshot_captured_by_cutoff": bool(feature.get("market_snapshot_captured_by_cutoff")),
            "market_snapshot_is_dual_time_feature_authority": False,
        })

    known = sum(1 for row in output_rows if row["resolved_label"] != "UNKNOWN")
    total = len(output_rows)
    return {
        "status": "OBSERVED",
        "tables": tables,
        "row_count": total,
        "known_label_count": known,
        "label_coverage": known / total if total else None,
        "reason_counts": reason_counts,
        "feature_counts": feature_counts,
        "feature_coverage": {
            key: value / total if total else None for key, value in feature_counts.items()
        },
        "rows": output_rows,
        "rows_truncated": False,
        "bounded": {
            "limit": limit,
            "feature_horizon_seconds": feature_horizon_seconds,
            "query_count_max": 5,
        },
        "temporal_contract": {
            "cohort_matches_pattern_discovery_dataset_ordering": True,
            "labels_must_be_known_by_dataset_as_of": True,
            "features_require_observed_and_ingested_by_feature_as_of": True,
            "market_snapshots_have_no_independent_ingested_at": True,
            "market_snapshots_not_promoted_to_dual_time_features": True,
            "mid_is_not_mapped_to_held": True,
        },
        **AUTHORITY,
    }
