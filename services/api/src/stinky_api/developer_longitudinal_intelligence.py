"""Evidence-only developer/deployer longitudinal intelligence for investigations.

This module summarizes already observed entity history. A fresh developer is
NEW-UNKNOWN, not trusted or suspicious. Historical facts do not become risk,
quality, prediction, probability, confidence, or trade authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _outcome_counts(launches: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    for launch in launches:
        raw = str(launch.get("outcome_status") or "UNKNOWN").upper()
        key = raw if raw in counts else "UNKNOWN"
        counts[key] += 1
    return counts


def _funding_counterparties(
    funding_history: list[dict[str, Any]],
    entity_wallets: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in funding_history:
        source = str(row.get("source_wallet") or "").strip()
        destination = str(row.get("destination_wallet") or "").strip()
        if not source or not destination:
            continue
        if source in entity_wallets and destination not in entity_wallets:
            counterparty, direction = destination, "OUTBOUND"
        elif destination in entity_wallets and source not in entity_wallets:
            counterparty, direction = source, "INBOUND"
        else:
            continue
        key = f"{counterparty}:{direction}"
        item = stats.setdefault(key, {
            "wallet": counterparty,
            "direction": direction,
            "observation_count": 0,
            "first_observed_at": None,
            "last_observed_at": None,
        })
        item["observation_count"] += 1
        observed = _iso(row.get("observed_at"))
        if observed is not None:
            observed = str(observed)
            if item["first_observed_at"] is None or observed < item["first_observed_at"]:
                item["first_observed_at"] = observed
            if item["last_observed_at"] is None or observed > item["last_observed_at"]:
                item["last_observed_at"] = observed
    return sorted(stats.values(), key=lambda x: (-int(x["observation_count"]), str(x["wallet"])))[:limit]


async def developer_longitudinal_intelligence(
    session: AsyncSession,
    entity_id: UUID,
    *,
    current_mint: str | None,
    graph: dict[str, Any],
    history: dict[str, Any],
    funding_history: list[dict[str, Any]],
    launch_limit: int = 100,
    early_buyer_limit: int = 50,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Return bounded historical developer/deployer evidence at a temporal cutoff."""
    launch_limit = max(1, min(500, int(launch_limit)))
    early_buyer_limit = max(1, min(200, int(early_buyer_limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return {
            "status": "UNKNOWN",
            "entity_id": str(entity_id),
            "history_state": "UNKNOWN",
            "missing": ["valid_as_of"],
            "predictive_authority": False,
            "trade_signal": False,
            "evidence_only": True,
        }

    launch_source = history.get("launch_history") if isinstance(history, dict) else None
    source_records = launch_source.get("records") if isinstance(launch_source, dict) else None
    source_records = source_records if isinstance(source_records, list) else []
    current_mint = str(current_mint or "").strip() or None
    launches = [
        dict(row) for row in source_records
        if isinstance(row, dict) and (current_mint is None or str(row.get("mint") or "") != current_mint)
    ][:launch_limit]

    entity_wallet_rows = graph.get("wallets") if isinstance(graph, dict) else None
    entity_wallet_rows = entity_wallet_rows if isinstance(entity_wallet_rows, list) else []
    associated_wallets = []
    entity_wallets: set[str] = set()
    for row in entity_wallet_rows:
        if not isinstance(row, dict):
            continue
        wallet = str(row.get("wallet") or "").strip()
        if not wallet:
            continue
        entity_wallets.add(wallet)
        associated_wallets.append({
            "wallet": wallet,
            "role": row.get("role"),
            "link_reason": row.get("link_reason"),
            "first_seen_at": _iso(row.get("first_seen_at")),
            "last_seen_at": _iso(row.get("last_seen_at")),
            "evidence": row.get("evidence"),
        })

    recurring_buyers: list[dict[str, Any]] = []
    if launches:
        historical_mints = [str(row.get("mint")) for row in launches if row.get("mint")]
        if historical_mints:
            cutoff_clause = "AND mb.bought_at <= :as_of" if cutoff is not None else ""
            params: dict[str, Any] = {
                "mints": historical_mints,
                "limit": early_buyer_limit,
            }
            if cutoff is not None:
                params["as_of"] = cutoff
            try:
                rows = (
                    await session.execute(
                        text(f"""
                            SELECT mb.wallet,
                                   COUNT(DISTINCT mb.mint)::int AS historical_launch_count,
                                   MIN(mb.rank)::int AS best_rank,
                                   MIN(mb.bought_at) AS first_observed_at,
                                   MAX(mb.bought_at) AS last_observed_at,
                                   ARRAY_AGG(DISTINCT mb.mint ORDER BY mb.mint) AS mints
                            FROM migration_buyers mb
                            WHERE mb.mint = ANY(:mints)
                              {cutoff_clause}
                            GROUP BY mb.wallet
                            HAVING COUNT(DISTINCT mb.mint) >= 2
                            ORDER BY COUNT(DISTINCT mb.mint) DESC, MIN(mb.rank) ASC, mb.wallet ASC
                            LIMIT :limit
                        """),
                        params,
                    )
                ).mappings().all()
                for row in rows:
                    item = dict(row)
                    item["first_observed_at"] = _iso(item.get("first_observed_at"))
                    item["last_observed_at"] = _iso(item.get("last_observed_at"))
                    item["relationship"] = "REPEAT_HISTORICAL_EARLY_BUYER"
                    item["ownership_inferred"] = False
                    item["coordination_inferred"] = False
                    recurring_buyers.append(item)
            except Exception:
                recurring_buyers = []

    outcome_counts = _outcome_counts(launches)
    known_outcomes = sum(outcome_counts[k] for k in ("RUNNER", "HELD", "FADE"))
    funding_counterparties = _funding_counterparties(
        funding_history,
        entity_wallets,
        limit=min(early_buyer_limit, 100),
    )

    history_state = "KNOWN_HISTORY" if launches else "NEW-UNKNOWN"
    result: dict[str, Any] = {
        "status": "OBSERVED" if launches or associated_wallets or funding_history else "NEW-UNKNOWN",
        "entity_id": str(entity_id),
        "current_mint_excluded_from_history": current_mint is not None,
        "history_state": history_state,
        "fresh_entity_interpretation": "NEW-UNKNOWN" if not launches else None,
        "launch_history": {
            "historical_launch_count": len(launches),
            "records": launches,
            "outcome_counts": outcome_counts,
            "known_outcome_count": known_outcomes,
            "unknown_outcome_count": outcome_counts["UNKNOWN"],
        },
        "associated_wallets": {
            "count": len(associated_wallets),
            "records": associated_wallets,
            "ownership_inferred": False,
        },
        "funding_relationships": {
            "observation_count": len(funding_history),
            "counterparties": funding_counterparties,
            "ownership_inferred": False,
            "intent_inferred": False,
        },
        "recurring_early_buyers": {
            "count": len(recurring_buyers),
            "records": recurring_buyers,
            "coordination_inferred": False,
            "ownership_inferred": False,
        },
        "bounded": {
            "launch_limit": launch_limit,
            "early_buyer_limit": early_buyer_limit,
            "funding_observation_count": len(funding_history),
        },
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }
    if not launches:
        result["missing"] = ["prior_developer_launch_history"]
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
