"""Synthesize bounded entity history evidence for Genesis investigations.

This module combines independently persisted evidence surfaces without turning
observations into quality, risk, ownership, intent, prediction, or trading
signals. Each source retains its own evidence basis and unknown state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.developer_longitudinal_intelligence import developer_longitudinal_intelligence
from stinky_api.entity_history_contract import canonicalize_entity_history
from stinky_api.market_lifecycle_memory import canonical_outcome_from_event


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _parse_as_of(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _unknown_source(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "records": [], "missing": [reason]}


def _source_provenance(source: dict[str, Any], *, source_name: str, as_of: datetime | None) -> dict[str, Any]:
    """Expose provenance without inventing freshness or timestamps."""
    records = source.get("records") or []
    observed: list[str] = []
    ingested: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("observed_at", "first_seen_at", "first_launch_at"):
            value = record.get(key)
            if value is not None:
                observed.append(str(value)); break
        value = record.get("ingested_at")
        if value is not None:
            ingested.append(str(value))
    computed_at = source.get("computed_at")
    result = {
        "evidence_source": source_name,
        "evidence_basis": source.get("evidence_basis") or "UNKNOWN",
        "observed_at": {"first": min(observed) if observed else None, "last": max(observed) if observed else None},
        "ingested_at": {"first": min(ingested) if ingested else None, "last": max(ingested) if ingested else None},
        "computed_at": _iso(computed_at) if computed_at is not None else None,
        "freshness_status": "UNKNOWN",
    }
    if as_of is not None:
        result["as_of"] = as_of.isoformat(); result["freshness_status"] = "HISTORICAL_AS_OF"
    return result


async def synthesize_entity_history(session: AsyncSession, entity_id: UUID, *, graph: dict[str, Any], funding_history: list[dict[str, Any]], launch_limit: int = 100, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Combine independent entity evidence into one bounded descriptive record."""
    launch_limit = max(1, min(500, int(launch_limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return canonicalize_entity_history({
            "status": "KNOWN_ENTITY", "entity_id": str(entity_id),
            "launch_history": _unknown_source("invalid_as_of"), "behavior_fingerprint": _unknown_source("invalid_as_of"),
            "wallet_relationships": _unknown_source("invalid_as_of"), "funding_history": _unknown_source("invalid_as_of"),
            "developer_longitudinal": _unknown_source("invalid_as_of"), "evidence_only": True,
        })

    launch_clause = "AND l.observed_at <= :as_of" if cutoff is not None else ""
    event_clause = "AND e.occurred_at <= :as_of AND e.ingested_at <= :as_of" if cutoff is not None else ""
    launch_params: dict[str, Any] = {"entity_id": entity_id, "launch_limit": launch_limit}
    if cutoff is not None: launch_params["as_of"] = cutoff

    try:
        launch_rows = (await session.execute(text(f"""
            SELECT l.id, l.entity_id::text AS entity_id, l.deployer_wallet, l.mint,
                   l.event_id, l.observed_at, l.outcome_status AS mutable_outcome_status,
                   l.outcome_meta, l.created_at,
                   oe.event_id::text AS outcome_event_id, oe.event_type AS outcome_event_type,
                   oe.occurred_at AS outcome_observed_at, oe.ingested_at AS outcome_ingested_at,
                   oe.signature AS outcome_signature, oe.producer AS outcome_producer,
                   oe.payload AS outcome_event_payload
            FROM entity_launches l
            LEFT JOIN LATERAL (
                SELECT e.event_id, e.event_type, e.occurred_at, e.ingested_at,
                       e.signature, e.producer, e.payload
                FROM events e
                WHERE e.event_type = 'post_migration.tracking_completed'
                  AND e.payload->>'mint' = l.mint {event_clause}
                ORDER BY e.occurred_at DESC, e.ingested_at DESC
                LIMIT 1
            ) oe ON TRUE
            WHERE l.entity_id = :entity_id {launch_clause}
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :launch_limit
        """), launch_params)).mappings().all()
        launches = []
        for row in launch_rows:
            item = dict(row)
            event = None
            if item.get("outcome_event_id"):
                event = {
                    "event_id": item.get("outcome_event_id"), "event_type": item.get("outcome_event_type"),
                    "occurred_at": item.get("outcome_observed_at"), "ingested_at": item.get("outcome_ingested_at"),
                    "signature": item.get("outcome_signature"), "producer": item.get("outcome_producer"),
                    "payload": item.get("outcome_event_payload") if isinstance(item.get("outcome_event_payload"), dict) else {},
                }
            item["outcome_status"] = canonical_outcome_from_event(event)
            item["outcome_resolution_basis"] = "immutable_post_migration_tracking_completed_event" if item["outcome_status"] != "UNKNOWN" else "UNKNOWN"
            item["outcome_evidence_basis"] = "events:post_migration.tracking_completed" if event is not None else "UNKNOWN"
            item["mutable_outcome_status_is_historical_authority"] = False
            item["observed_at"] = _iso(item.get("observed_at")); item["created_at"] = _iso(item.get("created_at")); item["ingested_at"] = item.get("created_at")
            item["outcome_observed_at"] = _iso(item.get("outcome_observed_at")); item["outcome_ingested_at"] = _iso(item.get("outcome_ingested_at"))
            item.pop("outcome_event_payload", None)
            launches.append(item)
        launch_history = {"status": "OBSERVED", "records": launches, "evidence_basis": "entity_launches", "outcome_evidence_basis": "immutable_post_migration.tracking_completed_events"}
    except Exception:
        launch_history = _unknown_source("launch_history"); launch_history["evidence_basis"] = "unknown_table_or_query"

    behavior_params: dict[str, Any] = {"entity_id": entity_id}
    behavior_clause = "AND computed_at <= :as_of" if cutoff is not None else ""
    if cutoff is not None: behavior_params["as_of"] = cutoff
    try:
        row = (await session.execute(text(f"""
            SELECT fingerprint, computed_at FROM entity_behavior_fingerprints
            WHERE entity_id = :entity_id {behavior_clause}
            ORDER BY computed_at DESC LIMIT 1
        """), behavior_params)).mappings().first()
        if row is None:
            behavior = _unknown_source("behavior_fingerprint"); behavior["evidence_basis"] = "no_persisted_fingerprint"
        else:
            behavior = {"status": "OBSERVED", "fingerprint": row["fingerprint"], "computed_at": _iso(row["computed_at"]), "evidence_basis": "entity_behavior_fingerprints"}
    except Exception:
        behavior = _unknown_source("behavior_fingerprint"); behavior["evidence_basis"] = "unknown_table_or_query"

    relationships = {"status": "OBSERVED", "wallets": list(graph.get("wallets") or []), "records": list(graph.get("relationships") or []), "evidence_basis": "entity_wallets+wallet_relationships"}
    funding = {"status": "OBSERVED", "records": list(funding_history), "evidence_basis": "wallet_funding_observations+direct_transfer_observation"}

    for source_name, source in (("launch_history", launch_history), ("behavior_fingerprint", behavior), ("wallet_relationships", relationships), ("funding_history", funding)):
        source["provenance"] = _source_provenance(source, source_name=source_name, as_of=cutoff)

    prehistory: dict[str, Any] = {"status": "KNOWN_ENTITY", "entity_id": str(entity_id), "launch_history": launch_history, "behavior_fingerprint": behavior, "wallet_relationships": relationships, "funding_history": funding}
    try:
        developer_longitudinal = await developer_longitudinal_intelligence(
            session, entity_id, current_mint=None, graph=graph, history=prehistory,
            funding_history=funding_history, launch_limit=launch_limit,
            early_buyer_limit=min(100, launch_limit), as_of=cutoff,
        )
    except Exception:
        developer_longitudinal = {"status": "UNKNOWN", "entity_id": str(entity_id), "history_state": "UNKNOWN", "missing": ["developer_longitudinal_evidence"], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}

    history = {
        **prehistory, "developer_longitudinal": developer_longitudinal,
        "bounded": {"launch_limit": launch_limit, "wallet_limit": graph.get("bounded", {}).get("wallet_limit"), "relationship_limit": graph.get("bounded", {}).get("relationship_limit"), "funding_observation_limit": graph.get("bounded", {}).get("funding_observation_limit"), "developer_early_buyer_limit": min(100, launch_limit)},
        "evidence_only": True,
    }
    if cutoff is not None:
        history["as_of"] = cutoff.isoformat(); history["temporal_cutoff_enforced"] = True
    return canonicalize_entity_history(history)
