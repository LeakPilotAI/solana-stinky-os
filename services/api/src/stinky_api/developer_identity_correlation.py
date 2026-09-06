"""Temporal, evidence-only developer/deployer identity correlation.

Observed overlap is not ownership, coordination, intent, risk, quality, or a trade signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.developer_correlation_motifs import analyze_network_motifs
from stinky_api.developer_correlation_repetition import analyze_correlation_repetition
from stinky_api.developer_motif_outcome_context import motif_outcome_context


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


def _with_repetition(result: dict[str, Any]) -> dict[str, Any]:
    result["repetition_analysis"] = analyze_correlation_repetition(result)
    result["network_motifs"] = analyze_network_motifs(result)
    return result


async def correlate_developer_identity(
    session: AsyncSession,
    entity_id: UUID,
    *,
    graph: dict[str, Any],
    as_of: datetime | str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Correlate bounded observed relationships around one developer entity."""
    limit = max(1, min(200, int(limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return _with_repetition({"status": "UNKNOWN", "entity_id": str(entity_id), "missing": ["valid_as_of"], "evidence_only": True,
                "ownership_inferred": False, "coordination_inferred": False, "predictive_authority": False, "trade_signal": False})

    wallets = sorted({str(r.get("wallet")) for r in (graph.get("wallets") or []) if isinstance(r, dict) and r.get("wallet")})
    if not wallets:
        return _with_repetition({"status": "NEW-UNKNOWN", "entity_id": str(entity_id), "wallets": [], "shared_funders": [],
                "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [], "shared_relationship_structures": [],
                "missing": ["entity_wallets"], "bounded": {"limit": limit}, "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
                "ownership_inferred": False, "coordination_inferred": False, "risk_inferred": False, "quality_inferred": False,
                "predictive_authority": False, "trade_signal": False, "evidence_only": True})

    time_clause_f = "AND f.observed_at <= :as_of" if cutoff else ""
    time_clause_l = "AND l.observed_at <= :as_of" if cutoff else ""
    time_clause_b = "AND mb.bought_at <= :as_of" if cutoff else ""
    params: dict[str, Any] = {"entity_id": entity_id, "wallets": wallets, "limit": limit}
    if cutoff:
        params["as_of"] = cutoff

    shared_funders: list[dict[str, Any]] = []
    wallet_reuse: list[dict[str, Any]] = []
    deployer_buyer: list[dict[str, Any]] = []
    structures: list[dict[str, Any]] = []
    missing: list[str] = []

    try:
        rows = (await session.execute(text(f"""
            WITH my_funders AS (
                SELECT DISTINCT f.source_wallet AS funder
                FROM wallet_funding_observations f
                WHERE f.destination_wallet = ANY(:wallets) {time_clause_f}
            )
            SELECT f.source_wallet AS funder_wallet,
                   ew.entity_id::text AS other_entity_id,
                   COUNT(*)::int AS observation_count,
                   MIN(f.observed_at) AS first_observed_at,
                   MAX(f.observed_at) AS last_observed_at
            FROM wallet_funding_observations f
            JOIN my_funders mf ON mf.funder = f.source_wallet
            JOIN entity_wallets ew ON ew.wallet = f.destination_wallet
            WHERE ew.entity_id <> :entity_id {time_clause_f}
            GROUP BY f.source_wallet, ew.entity_id
            ORDER BY COUNT(*) DESC, MAX(f.observed_at) DESC
            LIMIT :limit
        """), params)).mappings().all()
        shared_funders = [{**dict(r), "first_observed_at": _iso(r.get("first_observed_at")), "last_observed_at": _iso(r.get("last_observed_at")),
                           "relationship": "SHARED_FUNDER_OBSERVED", "ownership_inferred": False, "coordination_inferred": False} for r in rows]
    except Exception:
        missing.append("shared_funder_observations")

    try:
        rows = (await session.execute(text(f"""
            SELECT ew.wallet, ew.entity_id::text AS other_entity_id, ew.role, ew.link_reason,
                   ew.first_seen_at, ew.last_seen_at
            FROM entity_wallets ew
            WHERE ew.wallet = ANY(:wallets) AND ew.entity_id <> :entity_id
              AND (:as_of IS NULL OR ew.first_seen_at <= :as_of)
            ORDER BY ew.first_seen_at ASC NULLS LAST, ew.wallet
            LIMIT :limit
        """), {**params, "as_of": cutoff})).mappings().all()
        wallet_reuse = [{**dict(r), "first_seen_at": _iso(r.get("first_seen_at")), "last_seen_at": _iso(r.get("last_seen_at")),
                         "relationship": "WALLET_REUSE_OBSERVED", "ownership_inferred": False} for r in rows]
    except Exception:
        missing.append("cross_entity_wallet_reuse")

    try:
        rows = (await session.execute(text(f"""
            WITH my_launches AS (
                SELECT mint, deployer_wallet FROM entity_launches l
                WHERE entity_id = :entity_id {time_clause_l}
            ), my_deployers AS (
                SELECT DISTINCT deployer_wallet FROM my_launches WHERE deployer_wallet IS NOT NULL
            )
            SELECT mb.wallet, ew.entity_id::text AS buyer_entity_id,
                   COUNT(DISTINCT mb.mint)::int AS launch_count,
                   MIN(mb.rank)::int AS best_rank,
                   MIN(mb.bought_at) AS first_observed_at,
                   MAX(mb.bought_at) AS last_observed_at
            FROM migration_buyers mb
            LEFT JOIN entity_wallets ew ON ew.wallet = mb.wallet
            WHERE mb.mint IN (SELECT mint FROM my_launches)
              AND mb.wallet IN (SELECT deployer_wallet FROM my_deployers)
              {time_clause_b}
            GROUP BY mb.wallet, ew.entity_id
            ORDER BY COUNT(DISTINCT mb.mint) DESC, MIN(mb.rank) ASC
            LIMIT :limit
        """), params)).mappings().all()
        deployer_buyer = [{**dict(r), "first_observed_at": _iso(r.get("first_observed_at")), "last_observed_at": _iso(r.get("last_observed_at")),
                           "relationship": "DEPLOYER_EARLY_BUYER_RECURRENCE_OBSERVED", "coordination_inferred": False, "ownership_inferred": False} for r in rows]
    except Exception:
        missing.append("deployer_early_buyer_recurrence")

    try:
        rows = (await session.execute(text("""
            SELECT wr.relationship_kind,
                   CASE WHEN wa.entity_id = :entity_id THEN wb.entity_id::text ELSE wa.entity_id::text END AS other_entity_id,
                   COUNT(*)::int AS edge_count,
                   SUM(COALESCE(wr.observation_count,0))::int AS observation_count,
                   MIN(wr.first_seen_at) AS first_observed_at,
                   MAX(wr.last_seen_at) AS last_observed_at
            FROM wallet_relationships wr
            LEFT JOIN entity_wallets wa ON wa.wallet = wr.wallet_a
            LEFT JOIN entity_wallets wb ON wb.wallet = wr.wallet_b
            WHERE (wa.entity_id = :entity_id OR wb.entity_id = :entity_id)
              AND (:as_of IS NULL OR wr.first_seen_at <= :as_of)
            GROUP BY wr.relationship_kind, other_entity_id
            HAVING CASE WHEN wa.entity_id = :entity_id THEN wb.entity_id::text ELSE wa.entity_id::text END IS NOT NULL
            ORDER BY COUNT(*) DESC, SUM(COALESCE(wr.observation_count,0)) DESC
            LIMIT :limit
        """), {**params, "as_of": cutoff})).mappings().all()
        structures = [{**dict(r), "first_observed_at": _iso(r.get("first_observed_at")), "last_observed_at": _iso(r.get("last_observed_at")),
                       "relationship": "SHARED_RELATIONSHIP_STRUCTURE_OBSERVED", "ownership_inferred": False, "coordination_inferred": False} for r in rows]
    except Exception:
        missing.append("shared_relationship_structures")

    result = {
        "status": "OBSERVED" if any((shared_funders, wallet_reuse, deployer_buyer, structures)) else ("UNKNOWN" if missing else "NEW-UNKNOWN"),
        "entity_id": str(entity_id), "wallets": wallets,
        "shared_funders": shared_funders,
        "cross_entity_wallet_reuse": wallet_reuse,
        "deployer_buyer_recurrence": deployer_buyer,
        "shared_relationship_structures": structures,
        "missing": missing,
        "bounded": {"limit": limit, "wallet_count": len(wallets)},
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "ownership_inferred": False, "coordination_inferred": False, "intent_inferred": False,
        "risk_inferred": False, "quality_inferred": False,
        "predictive_authority": False, "trade_signal": False, "evidence_only": True,
    }
    if cutoff:
        result["as_of"] = cutoff.isoformat(); result["temporal_cutoff_enforced"] = True
    result = _with_repetition(result)
    try:
        result["motif_outcome_context"] = await motif_outcome_context(
            session, entity_id, network_motifs=result.get("network_motifs") or {}, as_of=cutoff, launch_limit=limit
        )
    except Exception:
        result["motif_outcome_context"] = {
            "status": "UNKNOWN", "records": [], "missing": ["historical_motif_launch_outcomes"],
            "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "predictive_authority": False,
            "trade_signal": False, "risk_inferred": False, "quality_inferred": False, "evidence_only": True,
        }
    return result
