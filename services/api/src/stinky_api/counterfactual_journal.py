"""Temporal-safe counterfactual journal for shadow/paper evaluation.

The journal freezes what Genesis would have done using only evidence available at
T0, then may attach a strictly later canonical measured outcome. It never sends
orders, grants trading authority, or rewrites the frozen T0 decision with future
evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

AUTHORITY = {
    "interpretation": "COUNTERFACTUAL_JOURNAL_PAPER_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "predictive_authority": False,
    "trade_signal": False,
    "paper_only": True,
    "evidence_only": True,
}

_ALLOWED_ACTIONS = {"WOULD_ENTER", "WOULD_SKIP", "WOULD_WATCH"}
_ALLOWED_OUTCOMES = {"RUNNER", "HELD", "FADE"}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _unknown(mint: str | None, missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "mint": mint,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def build_counterfactual_journal_entry(
    decision: dict[str, Any],
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze one T0 paper decision and optionally attach a later outcome.

    Required T0 fields are ``mint``, ``decided_at``, ``action``, a non-empty
    ``evidence_snapshot``, and explicit ``temporal_cutoff_enforced=True`` plus
    ``future_evidence_used=False``. Missing evidence fails closed to UNKNOWN.
    """
    mint = str(decision.get("mint") or "").strip()
    decided_at = _dt(decision.get("decided_at"))
    action = str(decision.get("action") or "").strip().upper()
    evidence = decision.get("evidence_snapshot")

    missing: list[str] = []
    if not mint:
        missing.append("mint")
    if decided_at is None:
        missing.append("decided_at")
    if action not in _ALLOWED_ACTIONS:
        missing.append("valid_counterfactual_action")
    if not isinstance(evidence, dict) or not evidence:
        missing.append("frozen_t0_evidence_snapshot")
    if decision.get("temporal_cutoff_enforced") is not True:
        missing.append("temporal_cutoff_enforced")
    if decision.get("future_evidence_used") is not False:
        missing.append("future_evidence_excluded")
    if missing:
        return _unknown(mint or None, missing)

    assert decided_at is not None
    frozen_decision = {
        "action": action,
        "decided_at": decided_at.isoformat(),
        "evidence_snapshot": deepcopy(evidence),
        "reason_codes": deepcopy(decision.get("reason_codes") or []),
        "policy_version": decision.get("policy_version"),
        "temporal_cutoff_enforced": True,
        "future_evidence_used": False,
    }

    entry: dict[str, Any] = {
        "status": "OPEN" if outcome is None else "OBSERVED",
        "mint": mint,
        "decision": frozen_decision,
        "outcome": None,
        "outcome_attached_after_decision": False,
        "t0_decision_rewritten_by_outcome": False,
        **AUTHORITY,
    }
    if outcome is None:
        return entry

    label = str(outcome.get("label") or "").strip().upper()
    observed_at = _dt(outcome.get("completed_at") or outcome.get("observed_at"))
    outcome_missing: list[str] = []
    if outcome.get("canonical_classification") is not True:
        outcome_missing.append("canonical_measured_outcome")
    if label not in _ALLOWED_OUTCOMES:
        outcome_missing.append("classified_outcome")
    if observed_at is None:
        outcome_missing.append("outcome_observed_at")
    if outcome_missing:
        return _unknown(mint, outcome_missing, decision=frozen_decision)

    assert observed_at is not None
    if observed_at <= decided_at:
        return _unknown(
            mint,
            ["strictly_later_outcome_evidence"],
            decision=frozen_decision,
            temporal_violation=True,
            outcome_observed_at=observed_at.isoformat(),
        )

    entry["outcome"] = {
        "label": label,
        "observed_at": observed_at.isoformat(),
        "evidence_basis": outcome.get("evidence_basis"),
        "source_table": outcome.get("source_table"),
    }
    entry["outcome_attached_after_decision"] = True
    return entry
