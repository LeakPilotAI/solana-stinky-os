"""Exact-cohort provenance audit for Phase-10 research evidence.

This module intentionally mirrors the candidate ordering used by
``pattern_discovery_dataset``. It explains why a research row is labelled or
remains UNKNOWN and audits historical feature sources without backdating or
inventing a second timestamp that was never stored.
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

    ``mega_runner`` and ``runner`` both satisfy an explicit runner rule in the
    legacy measured-snapshot learner. ``fade`` is explicitly fade. ``mid`` is
    *not* equivalent to HELD and therefore remains UNKNOWN.
    """
    raw = str(value or "").strip().lower()
    if raw in {"mega_runner", "runner"}:
        return "RUNNER"
    if raw == "fade":
        return "FADE"
    return "UNKNOWN"


def canonical_completion_event_label(payload: Any) -> str:
    """Use a completion event as a label only when it explicitly carries one."""
    if not isinstance(payload, dict):
        return "UNKNOWN"
    raw = str(payload.get("outcome_status") or payload.get("outcome") or payload.get("status") or "UNKNOWN").upper()
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


async def audit_phase10_cohort_provenance(
    session: AsyncSession,
    *,
    limit: int = 200,
    feature_horizon_seconds: int = 300,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Audit the same bounded launch cohort used by Phase-10 dataset formation."""
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
        return {"status": "UNKNOWN", "failure_stage": "table_preflight", "error_type": type(exc).__name__, **AUTHORITY}

    names = (
        "entity_launches", "events", "token_outcomes", "market_snapshots",
        "market_outcome_observations", "developer_longitudinal_snapshots",
        "developer_correlation_snapshots",
    )
    tables = {name: bool(table_row and table_row.get(name)) for name in names}
    if not tables["entity_launches"] or not tables["events"]:
        return {"status": "BLOCKED", "tables": tables, "missing": [name for name in ("entity_launches", "events") if not tables[name]], **AUTHORITY}

    params = {"limit": limit, "dataset_as_of": cutoff, "feature_seconds": feature_horizon_seconds}
    try:
        cohort = (await session.execute(text("""
            SELECT l.id AS launch_id, l.entity_id::text AS entity_id, l.mint,
                   l.observed_at AS launch_observed_at, l.created_at AS launch_ingested_at,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of
            FROM entity_launches l
            WHERE l.mint IS NOT NULL
              AND l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
              AND l.created_at <= :dataset_as_of
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :limit
        """), params)).mappings().all()
    except Exception as exc:
        return {"status": "UNKNOWN", "tables": tables, "failure_stage": "cohort_query", "error_type": type(exc).__name__, **AUTHORITY}

    rows = [dict(row) for row in cohort]
    mints = [str(row["mint"]) for row in rows if row.get("mint")]
    if not mints:
        return {"status": "UNKNOWN", "tables": tables, "row_count": 0, "reason_counts": {}, "rows": [], **AUTHORITY}

    completion_by_mint: dict[str, dict[str, Any]] = {}
    try:
        completion_rows = (await session.execute(text("""
            SELECT DISTINCT ON (e.payload->>'mint')
                   e.payload->>'mint' AS mint, e.event_id::text AS event_id,
                   e.occurred_at, e.ingested_at, e.payload
            FROM events e
            WHERE e.event_type = 'post_migration.tracking_completed'
              AND e.payload->>'mint' = ANY(:mints)
              AND e.occurred_at <= :dataset_as_of
              AND e.ingested_at <= :dataset_as_of
            ORDER BY e.payload->>'mint', e.occurred_at DESC, e.ingested_at DESC
        """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
        completion_by_mint = {str(row["mint"]): dict(row) for row in completion_rows if row.get("mint")}
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
                WHERE mint = ANY(:mints) AND evaluated_at <= :dataset_as_of
            """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
            outcome_by_mint = {str(row["mint"]): dict(row) for row in outcome_rows if row.get("mint")}
        except Exception:
            outcome_by_mint = {}

    feature_counts = {
        "developer_dual_time_visible": 0,
        "correlation_dual_time_visible": 0,
        "lifecycle_dual_time_visible": 0,
        "market_snapshot_captured_by_cutoff": 0,
    }
    output_rows: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}

    for launch in rows:
        mint = str(launch.get("mint") or "")
        feature_as_of = launch.get("feature_as_of")
        completion = completion_by_mint.get(mint)
        token_outcome = outcome_by_mint.get(mint)
        event_label = canonical_completion_event_label((completion or {}).get("payload"))
        legacy_label = canonical_token_outcome_label((token_outcome or {}).get("label"))
        if event_label != "UNKNOWN":
            resolved_label, label_basis = event_label, "explicit_tracking_completed_outcome"
        elif legacy_label != "UNKNOWN":
            resolved_label, label_basis = legacy_label, "measured_token_outcomes_safe_mapping"
        elif completion is not None:
            resolved_label, label_basis = "UNKNOWN", "tracking_completed_has_no_canonical_outcome"
        elif token_outcome is not None:
            resolved_label, label_basis = "UNKNOWN", "token_outcome_not_semantically_canonical"
        else:
            resolved_label, label_basis = "UNKNOWN", "no_label_evidence"
        reason_counts[label_basis] = reason_counts.get(label_basis, 0) + 1

        developer_visible = False
        correlation_visible = False
        lifecycle_visible = False
        snapshot_by_cutoff = False
        if feature_as_of is not None:
            if tables["developer_longitudinal_snapshots"]:
                developer_visible = bool((await session.execute(text("""
                    SELECT EXISTS(
                        SELECT 1 FROM developer_longitudinal_snapshots s
                        WHERE s.entity_id = CAST(:entity_id AS UUID)
                          AND s.observed_at <= :feature_as_of AND s.ingested_at <= :feature_as_of
                    )
                """), {"entity_id": launch["entity_id"], "feature_as_of": feature_as_of})).scalar())
            if tables["developer_correlation_snapshots"]:
                correlation_visible = bool((await session.execute(text("""
                    SELECT EXISTS(
                        SELECT 1 FROM developer_correlation_snapshots s
                        WHERE s.entity_id = CAST(:entity_id AS UUID)
                          AND s.observed_at <= :feature_as_of AND s.ingested_at <= :feature_as_of
                    )
                """), {"entity_id": launch["entity_id"], "feature_as_of": feature_as_of})).scalar())
            if tables["market_outcome_observations"]:
                lifecycle_visible = bool((await session.execute(text("""
                    SELECT EXISTS(
                        SELECT 1 FROM market_outcome_observations o
                        WHERE o.mint = :mint
                          AND o.observed_at <= :feature_as_of AND o.ingested_at <= :feature_as_of
                    )
                """), {"mint": mint, "feature_as_of": feature_as_of})).scalar())
            if tables["market_snapshots"]:
                snapshot_by_cutoff = bool((await session.execute(text("""
                    SELECT EXISTS(
                        SELECT 1 FROM market_snapshots s
                        WHERE s.mint = :mint AND s.captured_at <= :feature_as_of
                    )
                """), {"mint": mint, "feature_as_of": feature_as_of})).scalar())

        feature_counts["developer_dual_time_visible"] += int(developer_visible)
        feature_counts["correlation_dual_time_visible"] += int(correlation_visible)
        feature_counts["lifecycle_dual_time_visible"] += int(lifecycle_visible)
        feature_counts["market_snapshot_captured_by_cutoff"] += int(snapshot_by_cutoff)
        output_rows.append({
            "mint": mint,
            "entity_id": launch.get("entity_id"),
            "launch_observed_at": launch.get("launch_observed_at").isoformat() if hasattr(launch.get("launch_observed_at"), "isoformat") else launch.get("launch_observed_at"),
            "feature_as_of": feature_as_of.isoformat() if hasattr(feature_as_of, "isoformat") else feature_as_of,
            "completion_event_present": completion is not None,
            "completion_event_has_explicit_canonical_outcome": event_label != "UNKNOWN",
            "token_outcome_present": token_outcome is not None,
            "token_outcome_raw_label": (token_outcome or {}).get("label"),
            "resolved_label": resolved_label,
            "label_basis": label_basis,
            "developer_dual_time_visible": developer_visible,
            "correlation_dual_time_visible": correlation_visible,
            "lifecycle_dual_time_visible": lifecycle_visible,
            "market_snapshot_captured_by_cutoff": snapshot_by_cutoff,
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
        "feature_coverage": {key: value / total if total else None for key, value in feature_counts.items()},
        "rows": output_rows,
        "rows_truncated": False,
        "bounded": {"limit": limit, "feature_horizon_seconds": feature_horizon_seconds},
        "temporal_contract": {
            "cohort_matches_pattern_discovery_dataset_ordering": True,
            "labels_known_by_dataset_as_of": True,
            "features_require_observed_and_ingested_by_feature_as_of": True,
            "market_snapshots_have_no_independent_ingested_at": True,
            "market_snapshots_not_promoted_to_dual_time_features": True,
            "mid_is_not_mapped_to_held": True,
        },
        **AUTHORITY,
    }
