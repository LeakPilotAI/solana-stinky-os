"""Descriptive cross-entity constellation and historical motif analysis.

A motif is repeated observed structure, not proof of common ownership, coordination,
fraud, intent, risk, quality, probability, expected return, or a trade signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "ownership_inferred": False,
    "coordination_inferred": False,
    "intent_inferred": False,
    "fraud_inferred": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "predictive_authority": False,
    "trade_signal": False,
    "evidence_only": True,
}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _span_seconds(values: list[Any]) -> int | None:
    dts = [v for v in (_dt(x) for x in values) if v is not None]
    if len(dts) < 2:
        return 0 if len(dts) == 1 else None
    return max(0, int((max(dts) - min(dts)).total_seconds()))


def _repetition_lookup(correlation: dict[str, Any]) -> dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]]:
    repetition = correlation.get("repetition_analysis") if isinstance(correlation.get("repetition_analysis"), dict) else {}
    out: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}
    for row in repetition.get("records") or []:
        if not isinstance(row, dict):
            continue
        identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
        key = (str(row.get("kind") or ""), tuple(sorted((str(k), str(v or "")) for k, v in identity.items())))
        out[key] = row
    return out


def _rep(rep: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]], kind: str, identity: dict[str, Any]) -> dict[str, Any] | None:
    key = (kind, tuple(sorted((str(k), str(v or "")) for k, v in identity.items())))
    return rep.get(key)


def analyze_network_motifs(correlation: dict[str, Any]) -> dict[str, Any]:
    """Find recurring multi-entity structures in already cutoff-safe correlation evidence."""
    rep = _repetition_lookup(correlation)
    by_entity: dict[str, list[dict[str, Any]]] = {}
    funders: dict[str, list[dict[str, Any]]] = {}

    def add_entity(entity_id: Any, component: dict[str, Any]) -> None:
        key = str(entity_id or "").strip()
        if key:
            by_entity.setdefault(key, []).append(component)

    for row in correlation.get("shared_funders") or []:
        if not isinstance(row, dict): continue
        identity = {"funder_wallet": row.get("funder_wallet"), "other_entity_id": row.get("other_entity_id")}
        r = _rep(rep, "SHARED_FUNDER", identity)
        component = {"kind": "SHARED_FUNDER", "identity": identity, "repetition": r}
        add_entity(row.get("other_entity_id"), component)
        funder = str(row.get("funder_wallet") or "").strip()
        if funder:
            funders.setdefault(funder, []).append({"other_entity_id": row.get("other_entity_id"), "row": row, "repetition": r})

    for row in correlation.get("cross_entity_wallet_reuse") or []:
        if not isinstance(row, dict): continue
        identity = {"wallet": row.get("wallet"), "other_entity_id": row.get("other_entity_id")}
        add_entity(row.get("other_entity_id"), {"kind": "WALLET_REUSE", "identity": identity, "repetition": _rep(rep, "WALLET_REUSE", identity)})

    for row in correlation.get("shared_relationship_structures") or []:
        if not isinstance(row, dict): continue
        identity = {"relationship_kind": row.get("relationship_kind"), "other_entity_id": row.get("other_entity_id")}
        add_entity(row.get("other_entity_id"), {"kind": "RELATIONSHIP_STRUCTURE", "identity": identity, "repetition": _rep(rep, "RELATIONSHIP_STRUCTURE", identity)})

    for row in correlation.get("deployer_buyer_recurrence") or []:
        if not isinstance(row, dict): continue
        identity = {"wallet": row.get("wallet"), "buyer_entity_id": row.get("buyer_entity_id")}
        add_entity(row.get("buyer_entity_id"), {"kind": "DEPLOYER_BUYER_RECURRENCE", "identity": identity, "repetition": _rep(rep, "DEPLOYER_BUYER_RECURRENCE", identity)})

    motifs: list[dict[str, Any]] = []
    for other_entity_id, components in sorted(by_entity.items()):
        kinds = sorted({str(c.get("kind") or "") for c in components if c.get("kind")})
        repeated = [c for c in components if isinstance(c.get("repetition"), dict) and c["repetition"].get("repetition_state") in {"REPEATED_OBSERVATION", "MULTI_LAUNCH_REPETITION"}]
        multi_launch = [c for c in components if isinstance(c.get("repetition"), dict) and c["repetition"].get("repetition_state") == "MULTI_LAUNCH_REPETITION"]
        times: list[Any] = []
        observation_total = 0
        observation_known = False
        for c in components:
            r = c.get("repetition") if isinstance(c.get("repetition"), dict) else {}
            times.extend([r.get("first_observed_at"), r.get("last_observed_at")])
            if r.get("independent_observation_count") is not None:
                observation_total += int(r.get("independent_observation_count") or 0); observation_known = True
        if len(kinds) < 2 and not repeated and not multi_launch:
            continue
        state = "MULTI_LAUNCH_MOTIF" if multi_launch else ("REPEATED_MULTI_COMPONENT_MOTIF" if len(kinds) >= 2 and repeated else ("MULTI_COMPONENT_CONSTELLATION" if len(kinds) >= 2 else "REPEATED_SINGLE_COMPONENT_MOTIF"))
        motifs.append({
            "motif_kind": "CROSS_ENTITY_RELATIONSHIP_MOTIF",
            "other_entity_ids": [other_entity_id],
            "component_kinds": kinds,
            "component_count": len(components),
            "repeated_component_count": len(repeated),
            "multi_launch_component_count": len(multi_launch),
            "independent_observation_count": observation_total if observation_known else None,
            "temporal_spread_seconds": _span_seconds(times),
            "motif_state": state,
            "components": components,
            **AUTHORITY,
        })

    for funder, rows in sorted(funders.items()):
        entity_ids = sorted({str(r.get("other_entity_id") or "").strip() for r in rows if r.get("other_entity_id")})
        if len(entity_ids) < 2:
            continue
        repetitions = [r.get("repetition") for r in rows if isinstance(r.get("repetition"), dict)]
        times: list[Any] = []
        obs_total = 0
        obs_known = False
        for r in repetitions:
            times.extend([r.get("first_observed_at"), r.get("last_observed_at")])
            if r.get("independent_observation_count") is not None:
                obs_total += int(r.get("independent_observation_count") or 0); obs_known = True
        motifs.append({
            "motif_kind": "SHARED_FUNDER_CONSTELLATION",
            "funder_wallet": funder,
            "other_entity_ids": entity_ids,
            "component_kinds": ["SHARED_FUNDER"],
            "component_count": len(rows),
            "repeated_component_count": sum(1 for r in repetitions if r.get("repetition_state") in {"REPEATED_OBSERVATION", "MULTI_LAUNCH_REPETITION"}),
            "multi_launch_component_count": sum(1 for r in repetitions if r.get("repetition_state") == "MULTI_LAUNCH_REPETITION"),
            "independent_observation_count": obs_total if obs_known else None,
            "temporal_spread_seconds": _span_seconds(times),
            "motif_state": "MULTI_ENTITY_FUNDER_CONSTELLATION",
            **AUTHORITY,
        })

    motifs.sort(key=lambda m: (-len(m.get("other_entity_ids") or []), -int(m.get("component_count") or 0), str(m.get("motif_kind") or ""), str(m.get("other_entity_ids") or [])))
    repeated_motifs = [m for m in motifs if int(m.get("repeated_component_count") or 0) > 0]
    multi_launch_motifs = [m for m in motifs if int(m.get("multi_launch_component_count") or 0) > 0]
    return {
        "status": "OBSERVED" if motifs else ("UNKNOWN" if correlation.get("status") == "UNKNOWN" else "NEW-UNKNOWN"),
        "motif_count": len(motifs),
        "repeated_motif_count": len(repeated_motifs),
        "multi_launch_motif_count": len(multi_launch_motifs),
        "multi_entity_constellation_count": sum(1 for m in motifs if len(m.get("other_entity_ids") or []) >= 2),
        "records": motifs,
        "motif_is_not_ownership_or_coordination": True,
        "motif_is_not_risk_or_quality_score": True,
        **AUTHORITY,
    }
