"""Historical market-snapshot provenance audit for Phase-10 research.

The audit is read-only. It asks whether a market snapshot visible by a historical
feature cutoff also has independently persisted Event Log provenance proving when
Genesis ingested that same observation. Capture time alone is never promoted to
an ingestion timestamp.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "HISTORICAL_MARKET_SNAPSHOT_PROVENANCE_ONLY",
    "historical_feature_reconstruction_authorized": False,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}

CLASS_DUAL_TIME_PROVEN = "DUAL_TIME_PROVEN"
CLASS_CAPTURE_TIME_ONLY = "CAPTURE_TIME_ONLY"
CLASS_AMBIGUOUS = "AMBIGUOUS_PROVENANCE"
CLASS_EVENT_LATE = "DURABLE_EVENT_AFTER_FEATURE_CUTOFF"
CLASS_NO_SNAPSHOT = "NO_SNAPSHOT"


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


async def audit_historical_market_snapshot_provenance(
    session: AsyncSession,
    *,
    limit: int = 200,
    feature_horizon_seconds: int = 300,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Audit exact Phase-10 cohort snapshots against immutable event provenance.

    One representative snapshot is selected per launch: the latest snapshot at or
    before feature_as_of. An independently persisted market-snapshot event proves
    dual time only when exactly one event matches mint + exact observed timestamp
    + source/pair/dex identity and the event itself was ingested by feature_as_of.
    """
    limit = max(1, min(500, int(limit)))
    feature_horizon_seconds = max(0, min(1800, int(feature_horizon_seconds)))
    parsed_as_of = _parse(as_of)
    if as_of is not None and parsed_as_of is None:
        return {"status": "UNKNOWN", "missing": ["valid_as_of"], **AUTHORITY}
    cutoff = parsed_as_of or datetime.now(timezone.utc)

    try:
        preflight = (await session.execute(text("""
            SELECT
              to_regclass('entity_launches')::text AS entity_launches,
              to_regclass('market_snapshots')::text AS market_snapshots,
              to_regclass('events')::text AS events
        """))).mappings().first()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "failure_stage": "table_preflight",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    tables = {
        name: bool(preflight and preflight.get(name))
        for name in ("entity_launches", "market_snapshots", "events")
    }
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
            SELECT l.id AS launch_id, l.mint,
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
            "class_counts": {},
            "rows": [],
            **AUTHORITY,
        }

    try:
        snapshots = (await session.execute(text("""
            SELECT DISTINCT ON (s.mint)
                   s.snapshot_id::text AS snapshot_id, s.mint, s.captured_at,
                   s.price_usd, s.liquidity_usd, s.volume_m5_usd,
                   s.market_cap_usd, s.pair_address, s.dex_id, s.source,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of
            FROM market_snapshots s
            JOIN entity_launches l ON l.mint = s.mint
            WHERE s.mint = ANY(:mints)
              AND s.captured_at <= l.observed_at + make_interval(secs => :feature_seconds)
              AND s.captured_at <= :dataset_as_of
            ORDER BY s.mint, s.captured_at DESC, s.snapshot_id DESC
        """), {**params, "mints": mints})).mappings().all()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "tables": tables,
            "row_count": len(rows),
            "failure_stage": "snapshot_query",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    snapshot_by_mint = {str(row["mint"]): dict(row) for row in snapshots}

    try:
        event_rows = (await session.execute(text("""
            SELECT e.event_id::text AS event_id, e.payload->>'mint' AS mint,
                   e.occurred_at, e.ingested_at, e.producer, e.payload,
                   s.snapshot_id::text AS snapshot_id
            FROM events e
            JOIN market_snapshots s
              ON e.payload->>'mint' = s.mint
             AND e.occurred_at = s.captured_at
             AND (e.payload->>'source') IS NOT DISTINCT FROM s.source
             AND (e.payload->>'pair_address') IS NOT DISTINCT FROM s.pair_address
             AND (e.payload->>'dex_id') IS NOT DISTINCT FROM s.dex_id
            WHERE e.event_type = 'post_migration.market_snapshot'
              AND e.payload->>'mint' = ANY(:mints)
              AND e.occurred_at <= :dataset_as_of
              AND e.ingested_at <= :dataset_as_of
        """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "tables": tables,
            "row_count": len(rows),
            "failure_stage": "event_provenance_query",
            "error_type": type(exc).__name__,
            **AUTHORITY,
        }

    events_by_snapshot: dict[str, list[dict[str, Any]]] = {}
    for row in event_rows:
        events_by_snapshot.setdefault(str(row["snapshot_id"]), []).append(dict(row))

    output_rows: list[dict[str, Any]] = []
    class_counts = {
        CLASS_DUAL_TIME_PROVEN: 0,
        CLASS_CAPTURE_TIME_ONLY: 0,
        CLASS_AMBIGUOUS: 0,
        CLASS_EVENT_LATE: 0,
        CLASS_NO_SNAPSHOT: 0,
    }
    for launch in rows:
        mint = str(launch.get("mint") or "")
        snapshot = snapshot_by_mint.get(mint)
        if snapshot is None:
            classification = CLASS_NO_SNAPSHOT
            matches: list[dict[str, Any]] = []
        else:
            matches = events_by_snapshot.get(str(snapshot["snapshot_id"]), [])
            if len(matches) > 1:
                classification = CLASS_AMBIGUOUS
            elif len(matches) == 1:
                event = matches[0]
                feature_as_of = launch.get("feature_as_of")
                if feature_as_of is not None and event.get("ingested_at") is not None and event["ingested_at"] <= feature_as_of:
                    classification = CLASS_DUAL_TIME_PROVEN
                else:
                    classification = CLASS_EVENT_LATE
            else:
                classification = CLASS_CAPTURE_TIME_ONLY
        class_counts[classification] += 1

        first_event = matches[0] if len(matches) == 1 else None
        output_rows.append({
            "mint": mint,
            "launch_observed_at": _iso(launch.get("launch_observed_at")),
            "feature_as_of": _iso(launch.get("feature_as_of")),
            "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
            "snapshot_captured_at": _iso(snapshot.get("captured_at")) if snapshot else None,
            "snapshot_source": snapshot.get("source") if snapshot else None,
            "matching_immutable_event_count": len(matches),
            "matching_event_id": first_event.get("event_id") if first_event else None,
            "matching_event_ingested_at": _iso(first_event.get("ingested_at")) if first_event else None,
            "classification": classification,
            "historical_feature_reconstruction_authorized": classification == CLASS_DUAL_TIME_PROVEN,
        })

    total = len(output_rows)
    proven = class_counts[CLASS_DUAL_TIME_PROVEN]
    captured = total - class_counts[CLASS_NO_SNAPSHOT]
    return {
        "status": "OBSERVED",
        "tables": tables,
        "row_count": total,
        "snapshot_by_feature_cutoff_count": captured,
        "snapshot_by_feature_cutoff_coverage": captured / total if total else None,
        "dual_time_proven_count": proven,
        "dual_time_proven_coverage": proven / total if total else None,
        "class_counts": class_counts,
        "rows": output_rows,
        "rows_truncated": False,
        "bounded": {
            "limit": limit,
            "feature_horizon_seconds": feature_horizon_seconds,
            "query_count_max": 4,
        },
        "matching_contract": {
            "event_type": "post_migration.market_snapshot",
            "exact_mint_required": True,
            "exact_observed_timestamp_required": True,
            "source_pair_dex_identity_required": True,
            "exactly_one_event_required": True,
            "event_ingested_by_feature_cutoff_required": True,
        },
        "historical_policy": {
            "captured_at_is_not_ingested_at": True,
            "capture_time_only_is_not_feature_authority": True,
            "ambiguous_provenance_is_not_feature_authority": True,
            "late_event_is_not_feature_authority": True,
            "only_dual_time_proven_is_reconstructable": True,
            "audit_performs_writes": False,
        },
        "collector_policy_context": {
            "current_market_snapshot_stream_emission_skipped": True,
            "current_market_snapshot_event_log_emission_skipped": True,
            "historical_events_are_checked_anyway": True,
        },
        **AUTHORITY,
    }
