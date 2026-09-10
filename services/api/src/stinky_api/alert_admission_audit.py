"""Read-only audit of the live Gate-1 -> intelligence -> alert admission funnel.

This module diagnoses why prospective alert candidates are not being emitted. It
never changes filters, thresholds, memory, policy, or execution authority.
UNKNOWN remains valid and missing evidence is reported rather than promoted.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

AUTHORITY = {
    "interpretation": "READ_ONLY_ALERT_ADMISSION_AUDIT",
    "read_only": True,
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "thresholds_changed": False,
    "unknown_promoted": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if x is not None]
    return []


def summarize_inspection_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    pipeline: Counter[str] = Counter()
    has_intelligence = 0
    alert_ok = 0
    fee_unknown = 0
    synthetic_unknown = 0
    rug_unknown = 0
    creator_unknown = 0
    wallets_unknown = 0

    for row in rows:
        reasons[str(row.get("alert_reason") or "NONE")] += 1
        pipeline[str(row.get("pipeline_status") or "UNKNOWN")] += 1
        if row.get("has_intelligence") is True:
            has_intelligence += 1
        if row.get("alert_ok") is True:
            alert_ok += 1
        if str(row.get("fee_status") or "UNKNOWN") != "VERIFIED":
            fee_unknown += 1
        if str(row.get("synthetic_level") or "UNKNOWN") == "UNKNOWN":
            synthetic_unknown += 1
        if str(row.get("rug_level") or "UNKNOWN") == "UNKNOWN":
            rug_unknown += 1
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        creator = evidence.get("creator") if isinstance(evidence.get("creator"), dict) else {}
        wallets = evidence.get("wallets") if isinstance(evidence.get("wallets"), dict) else {}
        if str(creator.get("status") or "UNKNOWN") == "UNKNOWN":
            creator_unknown += 1
        if str(wallets.get("status") or "UNKNOWN") == "UNKNOWN":
            wallets_unknown += 1
        for item in _as_list(row.get("missing_data")):
            missing[item] += 1

    total = len(rows)
    insufficient = reasons.get("INTELLIGENCE_INSUFFICIENT", 0)
    return {
        "status": "OBSERVED" if total else "UNKNOWN",
        "inspection_count": total,
        "alert_ok_count": alert_ok,
        "has_intelligence_count": has_intelligence,
        "intelligence_insufficient_count": insufficient,
        "alert_reasons": dict(reasons.most_common()),
        "pipeline_statuses": dict(pipeline.most_common()),
        "missing_fields": dict(missing.most_common()),
        "layer_unknown_counts": {
            "wallets": wallets_unknown,
            "creator": creator_unknown,
            "synthetic": synthetic_unknown,
            "rug": rug_unknown,
            "fees": fee_unknown,
        },
        "interpretation": (
            "NO_INSPECTIONS_IN_WINDOW" if total == 0
            else "INTELLIGENCE_ACQUISITION_OR_HISTORY_COVERAGE_BOTTLENECK" if insufficient == total and alert_ok == 0
            else "MIXED_ADMISSION_RESULTS"
        ),
        **AUTHORITY,
    }


async def audit_alert_admission(session, *, hours: float, as_of: datetime | None = None) -> dict[str, Any]:
    try:
        window_hours = float(hours)
    except (TypeError, ValueError):
        window_hours = 0.0
    if window_hours <= 0:
        return {"status": "UNKNOWN", "missing": ["positive_audit_window_hours"], **AUTHORITY}

    cutoff = as_of or datetime.now(timezone.utc)
    started = cutoff - timedelta(hours=window_hours)

    rows = (await session.execute(text("""
        SELECT inspected_at,pipeline_status,synthetic_level,rug_level,fee_status,
               has_intelligence,alert_ok,alert_reason,evidence,missing_data
        FROM market_inspections
        WHERE inspected_at >= :started AND inspected_at <= :cutoff
        ORDER BY inspected_at ASC,id ASC
    """), {"started": started, "cutoff": cutoff})).mappings().all()
    summary = summarize_inspection_rows([dict(r) for r in rows])

    event_rows = (await session.execute(text("""
        SELECT event_type,count(*)
        FROM events
        WHERE ingested_at >= :started AND ingested_at <= :cutoff
          AND event_type IN (
            'token.migrated','market.gate1_passed','market.deep_inspection_completed',
            'alert.candidate','post_migration.tracking_started','post_migration.tracking_completed'
          )
        GROUP BY event_type
    """), {"started": started, "cutoff": cutoff})).all()
    events = {str(k): int(v) for k, v in event_rows}

    buyer_rows = (await session.execute(text("""
        SELECT
          count(DISTINCT mi.mint) FILTER (WHERE mb.mint IS NOT NULL) AS mints_with_buyers,
          count(DISTINCT mi.mint) AS inspected_mints
        FROM market_inspections mi
        LEFT JOIN migration_buyers mb ON mb.mint=mi.mint
        WHERE mi.inspected_at >= :started AND mi.inspected_at <= :cutoff
    """), {"started": started, "cutoff": cutoff})).first()
    inspected_mints = int((buyer_rows[1] if buyer_rows else 0) or 0)
    with_buyers = int((buyer_rows[0] if buyer_rows else 0) or 0)

    smart_rows = (await session.execute(text("""
        SELECT count(DISTINCT mb.mint)
        FROM market_inspections mi
        JOIN migration_buyers mb ON mb.mint=mi.mint
        JOIN wallet_performance wp ON wp.wallet=mb.wallet
        WHERE mi.inspected_at >= :started AND mi.inspected_at <= :cutoff
          AND COALESCE(wp.early_buy_count,0) >= 3
          AND COALESCE(wp.tokens_purchased,0) >= 3
          AND (wp.hit_rate IS NOT NULL OR COALESCE(wp.early_success_sample,0) >= 3)
    """), {"started": started, "cutoff": cutoff})).scalar_one()

    creator_rows = (await session.execute(text("""
        SELECT count(DISTINCT mi.mint)
        FROM market_inspections mi
        JOIN intelligence_investigations inv ON inv.mint=mi.mint
        JOIN entity_wallets ew ON ew.wallet=inv.creator
        JOIN entities e ON e.entity_id=ew.entity_id
        WHERE mi.inspected_at >= :started AND mi.inspected_at <= :cutoff
          AND COALESCE(e.launch_count,0) >= 3
    """), {"started": started, "cutoff": cutoff})).scalar_one()

    return {
        **summary,
        "window": {"hours": window_hours, "started_at": started.isoformat(), "as_of": cutoff.isoformat()},
        "events": {
            "token_migrated": events.get("token.migrated", 0),
            "gate1_passed": events.get("market.gate1_passed", 0),
            "deep_inspection_completed": events.get("market.deep_inspection_completed", 0),
            "alert_candidate": events.get("alert.candidate", 0),
            "tracking_started": events.get("post_migration.tracking_started", 0),
            "tracking_completed": events.get("post_migration.tracking_completed", 0),
        },
        "history_coverage": {
            "inspected_mints": inspected_mints,
            "mints_with_early_buyers": with_buyers,
            "mints_with_qualifying_wallet_history": int(smart_rows or 0),
            "mints_with_qualifying_creator_history": int(creator_rows or 0),
        },
        "notes": [
            "Global fees are optional intelligence evidence and are not part of has_intelligence.",
            "has_intelligence requires a KNOWN wallet with measured prior edge or a KNOWN creator with >=3 prior launches.",
            "This report does not lower or change any admission threshold.",
        ],
    }
