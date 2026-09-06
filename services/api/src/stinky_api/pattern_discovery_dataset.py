"""Temporal, evidence-only dataset formation for future pattern discovery.

Features are restricted to evidence known by each row's feature cutoff. Labels are
stored separately and may resolve later, but must be known by the dataset as_of.
This module does not discover patterns, train models, score markets, or trade.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.phase10_cohort_provenance import canonical_token_outcome_label

FEATURE_HORIZONS = {"launch": 0, "5m": 300, "15m": 900, "30m": 1800}
CANONICAL_OUTCOMES = {"RUNNER", "HELD", "FADE", "UNKNOWN"}
AUTHORITY = {
    "interpretation": "DESCRIPTIVE_RESEARCH_DATASET_ONLY",
    "pattern_discovery_authority": False,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "evidence_only": True,
}


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


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_event_label(event: dict[str, Any] | None) -> str:
    """Completion is not an outcome unless the event explicitly says so."""
    if not isinstance(event, dict) or event.get("event_type") != "post_migration.tracking_completed":
        return "UNKNOWN"
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    value = str(
        payload.get("outcome_status")
        or payload.get("outcome")
        or payload.get("status")
        or "UNKNOWN"
    ).upper()
    return value if value in CANONICAL_OUTCOMES else "UNKNOWN"


def _resolve_label(
    event: dict[str, Any] | None,
    token_outcome: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]]:
    """Resolve a canonical label from explicit or safely mapped measured evidence."""
    event_label = _canonical_event_label(event)
    if event_label != "UNKNOWN":
        return event_label, "explicit_tracking_completed_outcome", {
            "event_id": event.get("event_id") if event else None,
            "observed_at": _iso(event.get("occurred_at")) if event else None,
            "ingested_at": _iso(event.get("ingested_at")) if event else None,
            "source_event": event.get("event_type") if event else None,
            "producer": event.get("producer") if event else None,
        }

    mapped = canonical_token_outcome_label((token_outcome or {}).get("label"))
    if mapped != "UNKNOWN":
        return mapped, "measured_token_outcomes_safe_mapping", {
            "event_id": None,
            "observed_at": _iso((token_outcome or {}).get("evaluated_at")),
            "ingested_at": _iso((token_outcome or {}).get("evaluated_at")),
            "source_event": "token_outcomes",
            "producer": "post_migration.success_learner",
            "legacy_label": (token_outcome or {}).get("label"),
            "snapshots_n": (token_outcome or {}).get("snapshots_n"),
        }

    if token_outcome is not None:
        basis = "token_outcome_not_semantically_canonical"
    elif event is not None:
        basis = "tracking_completed_has_no_canonical_outcome"
    else:
        basis = "no_label_evidence"
    return "UNKNOWN", basis, {
        "event_id": event.get("event_id") if event else None,
        "observed_at": _iso(event.get("occurred_at")) if event else None,
        "ingested_at": _iso(event.get("ingested_at")) if event else None,
        "source_event": event.get("event_type") if event else None,
        "producer": event.get("producer") if event else None,
        "legacy_label": (token_outcome or {}).get("label"),
    }


def _snapshot_feature(snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    return snapshot


def _lifecycle_feature(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_horizon: dict[str, dict[str, Any]] = {}
    for row in records:
        horizon = str(row.get("horizon") or "")
        if horizon not in {"5m", "15m", "30m", "1h", "4h", "24h"} or horizon in by_horizon:
            continue
        by_horizon[horizon] = {
            "horizon": horizon,
            "observed_at": _iso(row.get("observed_at")),
            "ingested_at": _iso(row.get("ingested_at")),
            "source": row.get("source"),
            "evidence_basis": row.get("evidence_basis"),
            "metrics": row.get("metrics") if isinstance(row.get("metrics"), dict) else {},
        }
    return {
        "observed_horizons": [h for h in ("5m", "15m", "30m", "1h", "4h", "24h") if h in by_horizon],
        "missing_horizons": [h for h in ("5m", "15m", "30m", "1h", "4h", "24h") if h not in by_horizon],
        "horizons": by_horizon,
    }


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {"row_count": 0, "label_coverage": None, "developer_snapshot_coverage": None, "correlation_snapshot_coverage": None, "lifecycle_any_coverage": None}
    labeled = sum(1 for r in rows if r.get("label", {}).get("outcome") != "UNKNOWN")
    developer = sum(1 for r in rows if r.get("features", {}).get("developer_snapshot") is not None)
    correlation = sum(1 for r in rows if r.get("features", {}).get("correlation_snapshot") is not None)
    lifecycle = sum(1 for r in rows if r.get("features", {}).get("market_lifecycle", {}).get("observed_horizons"))
    return {
        "row_count": total,
        "label_coverage": labeled / total,
        "developer_snapshot_coverage": developer / total,
        "correlation_snapshot_coverage": correlation / total,
        "lifecycle_any_coverage": lifecycle / total,
    }


async def form_pattern_discovery_dataset(
    session: AsyncSession,
    *,
    limit: int = 100,
    as_of: datetime | str | None = None,
    feature_horizon: str = "5m",
    min_rows: int = 20,
    min_label_coverage: float = 0.5,
    min_feature_source_coverage: float = 0.5,
) -> dict[str, Any]:
    """Build deterministic historical research rows without future feature leakage."""
    limit = max(1, min(500, int(limit)))
    min_rows = max(1, min(500, int(min_rows)))
    min_label_coverage = max(0.0, min(1.0, float(min_label_coverage)))
    min_feature_source_coverage = max(0.0, min(1.0, float(min_feature_source_coverage)))
    horizon = str(feature_horizon or "5m").lower()
    if horizon not in FEATURE_HORIZONS:
        return {"status": "UNKNOWN", "rows": [], "row_count": 0, "missing": ["valid_feature_horizon"], **AUTHORITY}
    cutoff = _parse(as_of) or datetime.now(timezone.utc)
    if as_of is not None and _parse(as_of) is None:
        return {"status": "UNKNOWN", "rows": [], "row_count": 0, "missing": ["valid_as_of"], **AUTHORITY}
    seconds = FEATURE_HORIZONS[horizon]
    params = {"limit": limit, "dataset_as_of": cutoff, "feature_seconds": seconds}

    try:
        candidates = (await session.execute(text("""
            SELECT l.id AS launch_id, l.entity_id::text AS entity_id, l.mint, l.deployer_wallet,
                   l.observed_at AS launch_observed_at, l.created_at AS launch_ingested_at,
                   l.observed_at + make_interval(secs => :feature_seconds) AS feature_as_of,
                   ds.evidence_hash AS developer_evidence_hash, ds.evidence AS developer_evidence,
                   ds.observed_at AS developer_observed_at, ds.ingested_at AS developer_ingested_at,
                   cs.evidence_hash AS correlation_evidence_hash, cs.evidence AS correlation_evidence,
                   cs.observed_at AS correlation_observed_at, cs.ingested_at AS correlation_ingested_at
            FROM entity_launches l
            LEFT JOIN LATERAL (
                SELECT s.evidence_hash, s.evidence, s.observed_at, s.ingested_at
                FROM developer_longitudinal_snapshots s
                WHERE s.entity_id = l.entity_id
                  AND s.observed_at <= l.observed_at + make_interval(secs => :feature_seconds)
                  AND s.ingested_at <= l.observed_at + make_interval(secs => :feature_seconds)
                ORDER BY s.observed_at DESC, s.id DESC LIMIT 1
            ) ds ON TRUE
            LEFT JOIN LATERAL (
                SELECT s.evidence_hash, s.evidence, s.observed_at, s.ingested_at
                FROM developer_correlation_snapshots s
                WHERE s.entity_id = l.entity_id
                  AND s.observed_at <= l.observed_at + make_interval(secs => :feature_seconds)
                  AND s.ingested_at <= l.observed_at + make_interval(secs => :feature_seconds)
                ORDER BY s.observed_at DESC, s.id DESC LIMIT 1
            ) cs ON TRUE
            WHERE l.mint IS NOT NULL
              AND l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of
              AND l.created_at <= :dataset_as_of
            ORDER BY l.observed_at DESC, l.id DESC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "rows": [], "row_count": 0, "missing": ["historical_launch_snapshot_evidence"], "bounded": {"limit": limit, "query_count": 1}, **AUTHORITY}

    launch_rows = [dict(r) for r in candidates]
    mints = sorted({str(r.get("mint")) for r in launch_rows if r.get("mint")})
    lifecycle_by_mint: dict[str, list[dict[str, Any]]] = {mint: [] for mint in mints}
    completion_by_mint: dict[str, dict[str, Any]] = {}
    token_outcomes_by_mint: dict[str, dict[str, Any]] = {}
    query_count = 1
    if mints:
        try:
            lifecycle_rows = (await session.execute(text("""
                SELECT o.mint, o.horizon, o.horizon_seconds, o.observed_at, o.ingested_at,
                       o.source, o.evidence_basis, o.metrics, o.event_id, o.signature
                FROM market_outcome_observations o
                JOIN entity_launches l ON l.mint = o.mint
                WHERE o.mint = ANY(:mints)
                  AND o.observed_at <= l.observed_at + make_interval(secs => :feature_seconds)
                  AND o.ingested_at <= l.observed_at + make_interval(secs => :feature_seconds)
                  AND o.observed_at <= :dataset_as_of AND o.ingested_at <= :dataset_as_of
                ORDER BY o.mint, o.horizon_seconds, o.observed_at, o.id
            """), {**params, "mints": mints})).mappings().all()
            for row in lifecycle_rows:
                lifecycle_by_mint.setdefault(str(row.get("mint")), []).append(dict(row))
        except Exception:
            lifecycle_by_mint = {mint: [] for mint in mints}
        query_count += 1

        try:
            label_rows = (await session.execute(text("""
                SELECT DISTINCT ON (e.payload->>'mint') e.payload->>'mint' AS mint,
                       e.event_id::text AS event_id, e.event_type, e.occurred_at, e.ingested_at,
                       e.signature, e.producer, e.payload
                FROM events e
                WHERE e.event_type = 'post_migration.tracking_completed'
                  AND e.payload->>'mint' = ANY(:mints)
                  AND e.occurred_at <= :dataset_as_of AND e.ingested_at <= :dataset_as_of
                ORDER BY e.payload->>'mint', e.occurred_at DESC, e.ingested_at DESC
            """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
            completion_by_mint = {str(r.get("mint")): dict(r) for r in label_rows}
        except Exception:
            completion_by_mint = {}
        query_count += 1

        try:
            outcome_rows = (await session.execute(text("""
                SELECT mint, label, evaluated_at, snapshots_n,
                       peak_volume_m5_usd, peak_liquidity_usd,
                       peak_market_cap_usd, peak_price_usd, notes
                FROM token_outcomes
                WHERE mint = ANY(:mints)
                  AND evaluated_at <= :dataset_as_of
            """), {"mints": mints, "dataset_as_of": cutoff})).mappings().all()
            token_outcomes_by_mint = {str(r.get("mint")): dict(r) for r in outcome_rows}
        except Exception:
            token_outcomes_by_mint = {}
        query_count += 1

    rows: list[dict[str, Any]] = []
    label_basis_counts: dict[str, int] = {}
    for launch in launch_rows:
        mint = str(launch.get("mint") or "")
        feature_as_of = launch.get("feature_as_of")
        event = completion_by_mint.get(mint)
        token_outcome = token_outcomes_by_mint.get(mint)
        label_outcome, label_basis, label_provenance = _resolve_label(event, token_outcome)
        label_basis_counts[label_basis] = label_basis_counts.get(label_basis, 0) + 1
        developer_snapshot = _snapshot_feature(launch.get("developer_evidence"))
        correlation_snapshot = _snapshot_feature(launch.get("correlation_evidence"))
        features = {
            "developer_snapshot": developer_snapshot,
            "correlation_snapshot": correlation_snapshot,
            "market_lifecycle": _lifecycle_feature(lifecycle_by_mint.get(mint, [])),
        }
        feature_provenance = {
            "developer": {"evidence_hash": launch.get("developer_evidence_hash"), "observed_at": _iso(launch.get("developer_observed_at")), "ingested_at": _iso(launch.get("developer_ingested_at"))},
            "correlation": {"evidence_hash": launch.get("correlation_evidence_hash"), "observed_at": _iso(launch.get("correlation_observed_at")), "ingested_at": _iso(launch.get("correlation_ingested_at"))},
        }
        label = {
            "outcome": label_outcome,
            "basis": label_basis,
            **label_provenance,
        }
        canonical = {
            "entity_id": launch.get("entity_id"), "mint": mint,
            "launch_observed_at": _iso(launch.get("launch_observed_at")),
            "feature_horizon": horizon, "feature_as_of": _iso(feature_as_of),
            "features": features, "feature_provenance": feature_provenance, "label": label,
        }
        rows.append({**canonical, "row_hash": _hash(canonical), "future_feature_leakage_allowed": False, **AUTHORITY})

    coverage = _coverage(rows)
    source_coverages = [coverage.get("developer_snapshot_coverage"), coverage.get("correlation_snapshot_coverage"), coverage.get("lifecycle_any_coverage")]
    source_coverages = [float(v) for v in source_coverages if v is not None]
    formation_ready = (
        len(rows) >= min_rows
        and coverage.get("label_coverage") is not None
        and float(coverage["label_coverage"]) >= min_label_coverage
        and bool(source_coverages)
        and min(source_coverages) >= min_feature_source_coverage
    )
    dataset_identity = {"as_of": cutoff.isoformat(), "feature_horizon": horizon, "row_hashes": [r["row_hash"] for r in rows]}
    return {
        "status": "OBSERVED" if rows else "UNKNOWN",
        "formation_status": "READY_FOR_DESCRIPTIVE_DISCOVERY" if formation_ready else "INSUFFICIENT_EVIDENCE",
        "dataset_hash": _hash(dataset_identity),
        "as_of": cutoff.isoformat(), "feature_horizon": horizon,
        "rows": rows, "row_count": len(rows), "coverage": coverage,
        "label_basis_counts": label_basis_counts,
        "criteria": {"min_rows": min_rows, "min_label_coverage": min_label_coverage, "min_feature_source_coverage": min_feature_source_coverage},
        "bounded": {"limit": limit, "query_count": query_count},
        "temporal_contract": {
            "features_must_be_known_by_feature_as_of": True,
            "labels_must_be_known_by_dataset_as_of": True,
            "labels_may_resolve_after_feature_as_of": True,
            "tracking_completed_without_explicit_outcome_is_not_a_label": True,
            "legacy_mid_is_not_mapped_to_held": True,
        },
        **AUTHORITY,
    }
