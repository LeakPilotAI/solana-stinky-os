"""Canonical contract for bounded, evidence-only entity history.

The contract deliberately contains descriptive observations only. It does not
encode quality, risk, ownership, intent, prediction, or trading decisions.
"""

from __future__ import annotations

from typing import Any


_SOURCE_KEYS = (
    "launch_history",
    "behavior_fingerprint",
    "wallet_relationships",
    "funding_history",
)


def _unknown_provenance(source_name: str) -> dict[str, Any]:
    return {
        "evidence_source": source_name,
        "evidence_basis": "UNKNOWN",
        "observed_at": {"first": None, "last": None},
        "ingested_at": {"first": None, "last": None},
        "computed_at": None,
        "freshness_status": "UNKNOWN",
    }


def canonicalize_entity_history(history: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, bounded contract for downstream investigation consumers."""
    bounded = dict(history.get("bounded") or {})
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for key in _SOURCE_KEYS:
        source = dict(history.get(key) or {})
        source.setdefault("status", "UNKNOWN")
        source.setdefault("records", [])
        source.setdefault("provenance", _unknown_provenance(key))
        if source.get("status") == "UNKNOWN":
            missing.extend(str(item) for item in (source.get("missing") or [key]))
        sources[key] = source

    missing = list(dict.fromkeys(missing))
    result = {
        "status": str(history.get("status") or "UNKNOWN"),
        "entity_id": history.get("entity_id"),
        "sources": sources,
        "bounded": bounded,
        "missing": missing,
        "evidence_only": True,
    }
    if history.get("as_of") is not None:
        result["as_of"] = history["as_of"]
        result["temporal_cutoff_enforced"] = bool(history.get("temporal_cutoff_enforced", False))
    return result
