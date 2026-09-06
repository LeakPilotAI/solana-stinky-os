"""Describe longitudinal calibration-state transitions from persisted evidence.

This layer consumes immutable calibration snapshots only. It describes state runs,
transitions, persistence, and observed degradation recovery without producing a
prediction, probability, confidence, quality/risk score, or trading authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

KNOWN_STATES = {"STABLE", "IMPROVING", "DEGRADING", "INSUFFICIENT_EVIDENCE"}


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _unknown(reason: str, pattern_hash: str | None = None) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "current_state": "INSUFFICIENT_EVIDENCE",
        "snapshot_count": 0,
        "state_run_count": 0,
        "transition_count": 0,
        "state_runs": [],
        "transitions": [],
        "degradation_episode_count": 0,
        "recovered_degradation_episode_count": 0,
        "open_degradation_episode": False,
        "missing": [reason],
        "evidence_basis": "persisted_market_pattern_calibration_snapshots",
        "evidence_only": True,
    }


def describe_calibration_state_transitions(memory: dict[str, Any]) -> dict[str, Any]:
    """Collapse chronological snapshots into durable state runs and transitions."""
    pattern_hash = memory.get("pattern_hash") if isinstance(memory, dict) else None
    if not isinstance(memory, dict) or memory.get("status") != "OBSERVED":
        return _unknown("market_pattern_calibration_snapshots", pattern_hash)

    dated: list[tuple[datetime, int, str, dict[str, Any]]] = []
    for record in memory.get("records", []):
        if not isinstance(record, dict):
            continue
        state = str(record.get("trend_status") or "").strip()
        observed_at = _time(record.get("evidence_through_observed_at"))
        if state not in KNOWN_STATES or observed_at is None:
            continue
        dated.append((observed_at, int(record.get("id") or 0), state, record))
    dated.sort(key=lambda item: (item[0], item[1]))
    if not dated:
        return _unknown("valid_calibration_snapshot_states", pattern_hash)

    runs: list[dict[str, Any]] = []
    for observed_at, snapshot_id, state, _ in dated:
        if not runs or runs[-1]["state"] != state:
            runs.append({
                "state": state,
                "first_evidence_through_observed_at": observed_at.isoformat(),
                "last_evidence_through_observed_at": observed_at.isoformat(),
                "snapshot_count": 1,
                "first_snapshot_id": snapshot_id or None,
                "last_snapshot_id": snapshot_id or None,
                "evidence_only": True,
            })
        else:
            run = runs[-1]
            run["last_evidence_through_observed_at"] = observed_at.isoformat()
            run["snapshot_count"] += 1
            run["last_snapshot_id"] = snapshot_id or run["last_snapshot_id"]

    transitions: list[dict[str, Any]] = []
    degradation_episode_count = 0
    recovered_degradation_episode_count = 0
    open_degradation = False
    for index in range(1, len(runs)):
        previous = runs[index - 1]
        current = runs[index]
        from_state = previous["state"]
        to_state = current["state"]
        transition = {
            "transition_index": index,
            "from_state": from_state,
            "to_state": to_state,
            "transition": f"{from_state}->{to_state}",
            "observed_at": current["first_evidence_through_observed_at"],
            "prior_state_snapshot_count": previous["snapshot_count"],
            "evidence_only": True,
        }
        transitions.append(transition)
        if to_state == "DEGRADING" and from_state != "DEGRADING":
            degradation_episode_count += 1
            open_degradation = True
        elif open_degradation and from_state == "DEGRADING" and to_state in {"STABLE", "IMPROVING"}:
            recovered_degradation_episode_count += 1
            open_degradation = False

    if runs[0]["state"] == "DEGRADING":
        degradation_episode_count += 1
        open_degradation = True
        if len(runs) > 1 and runs[1]["state"] in {"STABLE", "IMPROVING"}:
            recovered_degradation_episode_count += 1
            open_degradation = False
    if runs[-1]["state"] != "DEGRADING":
        open_degradation = False

    result = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "current_state": runs[-1]["state"],
        "snapshot_count": len(dated),
        "state_run_count": len(runs),
        "transition_count": len(transitions),
        "state_runs": runs,
        "transitions": transitions,
        "degradation_episode_count": degradation_episode_count,
        "recovered_degradation_episode_count": recovered_degradation_episode_count,
        "open_degradation_episode": open_degradation,
        "missing": [],
        "evidence_basis": "persisted_market_pattern_calibration_snapshots",
        "evidence_only": True,
    }
    if memory.get("as_of") is not None:
        result["as_of"] = memory.get("as_of")
        result["temporal_cutoff_enforced"] = bool(memory.get("temporal_cutoff_enforced"))
    return result
