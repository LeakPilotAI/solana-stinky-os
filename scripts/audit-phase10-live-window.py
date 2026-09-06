"""Read-only windowed view over the prospective Phase-10 corpus audit."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from stinky_api.db import SessionLocal
from stinky_api.prospective_phase10_corpus import audit_prospective_phase10_corpus


def _parse(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _coverage(count: int, total: int) -> float | None:
    return count / total if total else None


def _summarize(result: dict[str, Any], *, since: datetime) -> dict[str, Any]:
    rows = []
    for row in result.get("rows") or []:
        if not isinstance(row, dict):
            continue
        observed = row.get("migration_observed_at")
        if not observed:
            continue
        try:
            observed_at = _parse(str(observed))
        except ValueError:
            continue
        if observed_at >= since:
            rows.append(row)

    total = len(rows)
    entity_count = sum(bool(r.get("entity_resolved")) for r in rows)
    developer_count = sum(bool(r.get("developer_dual_time_visible")) for r in rows)
    correlation_count = sum(bool(r.get("correlation_dual_time_visible")) for r in rows)
    lifecycle_count = sum(bool(r.get("lifecycle_dual_time_visible")) for r in rows)
    complete_count = sum(bool(r.get("feature_complete")) for r in rows)

    return {
        "status": "OBSERVED" if rows else "NO_ROWS_IN_WINDOW",
        "since": since.isoformat(),
        "row_count": total,
        "entity_resolved_count": entity_count,
        "entity_resolved_coverage": _coverage(entity_count, total),
        "developer_dual_time_count": developer_count,
        "developer_dual_time_coverage": _coverage(developer_count, total),
        "correlation_dual_time_count": correlation_count,
        "correlation_dual_time_coverage": _coverage(correlation_count, total),
        "lifecycle_dual_time_count": lifecycle_count,
        "lifecycle_dual_time_coverage": _coverage(lifecycle_count, total),
        "feature_complete_count": complete_count,
        "feature_complete_coverage": _coverage(complete_count, total),
        "rows": rows,
        "bounded": result.get("bounded"),
        "window_policy": {
            "basis": "migration_observed_at >= operator supplied since",
            "source": "audit_prospective_phase10_corpus",
            "writes": False,
            "historical_backfill": False,
            "dual_time_required_by_source_audit": True,
        },
        "interpretation": "PROSPECTIVE_PHASE10_CORPUS_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "probability_inferred": False,
        "confidence_inferred": False,
        "evidence_only": True,
    }


async def _run(limit: int, feature_horizon_seconds: int, since: datetime) -> None:
    async with SessionLocal() as session:
        result = await audit_prospective_phase10_corpus(
            session,
            limit=limit,
            feature_horizon_seconds=feature_horizon_seconds,
        )
        print(json.dumps(_summarize(result, since=since), indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a migration-time window within the prospective Phase-10 corpus."
    )
    parser.add_argument("--since", required=True, help="ISO-8601 migration observed-at lower bound")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--feature-horizon-seconds", type=int, default=300)
    args = parser.parse_args()
    try:
        since = _parse(args.since)
    except ValueError as exc:
        parser.error(f"invalid --since value: {exc}")
    asyncio.run(_run(args.limit, args.feature_horizon_seconds, since))


if __name__ == "__main__":
    main()
