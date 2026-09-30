"""Bounded, read-only database evidence for one explicitly selected paper cohort.

The limit is a resource bound, never an evidence-sufficiency threshold. Overflow
invalidates evaluation instead of silently evaluating a convenient subset.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import text

from stinky_api.paper_policy_identity import validated_policy_identity
from stinky_api.paper_runtime_worker import canonical_sha256
from stinky_api.paper_walk_forward_adapter import adapt_simulated_execution_for_walk_forward
from stinky_api.walk_forward_paper_validation import evaluate_walk_forward_paper
from stinky_api.prospective_paper_intake_producer import _ALLOWED_HORIZONS

AUTHORITY = {
    "paper_only": True, "read_only": True, "live_execution": False,
    "trading_authority": False, "trade_signal": False,
    "rpc_contacted": False, "transaction_signed": False, "order_submitted": False,
    "wallet_mutated": False, "automatic_activation": False,
    "thresholds_invented": False, "historical_identity_inference": False,
}

COHORT_SQL = text("""
    SELECT r.intake_id, r.mint, r.decided_at, r.created_at,
           r.policy_version, r.policy_sha256, r.policy_evidence_backed,
           r.paper_status, r.record, i.mint AS intake_mint, i.observed_at,
           i.created_at AS intake_created_at, i.payload, i.payload_sha256
    FROM paper_runtime_record r
    LEFT JOIN paper_runtime_intake i ON i.intake_id = r.intake_id
    WHERE r.policy_sha256 = :policy_sha256 AND r.created_at <= :as_of
    ORDER BY r.created_at ASC, r.intake_id ASC
    LIMIT :fetch_limit
""")


def _time(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe(value: Any) -> bool:
    return isinstance(value, dict) and value.get("paper_only") is True and all(
        value.get(key) is False for key in (
            "live_execution", "trading_authority", "trade_signal",
            "rpc_contacted", "transaction_signed", "order_submitted",
        )
    ) and all(value.get(key, False) is False for key in ("wallet_mutated", "recommendation_authority"))


async def report_paper_cohort(session, *, policy_sha256: Any = None,
                              policy_version: Any = None, evidence_backed: Any = None,
                              as_of: Any = None, record_limit: Any = 500,
                              release_criteria: Any = None) -> dict:
    """Select by SHA, then verify every returned version/provenance before use.

    Deliberately do not filter mismatched versions/provenance away in SQL: a
    conflicting identity under the selected SHA must invalidate the report.
    """
    selection = _selection_report(policy_sha256, policy_version, evidence_backed,
                                  as_of, record_limit, release_criteria)
    if "reasons" in selection:
        return selection
    try:
        rows = (await session.execute(COHORT_SQL, {
            "policy_sha256": policy_sha256, "as_of": _time(selection["as_of"]),
            "fetch_limit": record_limit + 1,
        })).mappings().all()
    except Exception:
        return {**selection, "reasons": ["cohort_evidence_unavailable"]}
    return evaluate_cohort_rows(rows, selection=selection, release_criteria=release_criteria)


def _selection_report(policy_sha256, policy_version, evidence_backed,
                      as_of, record_limit, release_criteria):
    result = {
        "status": "UNKNOWN", "scope": "SINGLE_IMMUTABLE_POLICY_COHORT",
        "selected_policy": {"policy_sha256": policy_sha256, "policy_version": policy_version,
                            "evidence_backed": evidence_backed},
        "release_criteria_supplied": release_criteria is not None,
        "walk_forward_evaluated": False, "walk_forward": None,
        "evaluation_artifact_produced": False, "evaluation_artifact": None,
        "structurally_eligible": False, "counts": None, "deficits": None,
        **AUTHORITY,
    }

    def unknown(reason: str, **extra) -> dict:
        return {**result, "reasons": [reason], **extra}

    cutoff = _time(as_of)
    if not isinstance(policy_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", policy_sha256):
        return unknown("explicit_valid_policy_sha256_required")
    if not isinstance(policy_version, str) or not policy_version.strip() or policy_version != policy_version.strip():
        return unknown("explicit_policy_version_required")
    if type(evidence_backed) is not bool:
        return unknown("explicit_evidence_backed_boolean_required")
    if cutoff is None:
        return unknown("explicit_timezone_aware_as_of_required")
    if type(record_limit) is not int or not 1 <= record_limit <= 2000:
        return unknown("record_limit_must_be_integer_1_to_2000")
    if release_criteria is not None and not isinstance(release_criteria, dict):
        return unknown("release_criteria_must_be_object")
    result.update(as_of=cutoff.isoformat(), record_limit=record_limit)
    return result


def evaluate_cohort_rows(rows, *, selection, release_criteria, produce_artifact=True):
    """Pure replay of stored evidence. No database, active policy, or wall clock."""
    result = deepcopy(selection)
    policy_sha256 = result["selected_policy"]["policy_sha256"]
    policy_version = result["selected_policy"]["policy_version"]
    evidence_backed = result["selected_policy"]["evidence_backed"]
    cutoff = _time(result["as_of"])
    record_limit = result["record_limit"]

    def unknown(reason: str, **extra) -> dict:
        return {**result, "reasons": [reason], **extra}

    if len(rows) > record_limit:
        return unknown("cohort_exceeds_record_limit", truncated=True)
    if not rows:
        return unknown("selected_cohort_not_found_as_of")

    identity = None
    closed = []
    seen = set()
    close_sources = set()
    counts = {"total_immutable_records": len(rows), "closed_simulations": 0,
              "open_simulation_records": 0, "not_simulated_records": 0}
    evidence_times = []
    for row in rows:
        record = row.get("record")
        payload = row.get("payload")
        current = validated_policy_identity(record.get("policy_identity")) if isinstance(record, dict) else None
        if (current is None or row.get("policy_sha256") != policy_sha256
                or row.get("policy_version") != policy_version
                or row.get("policy_evidence_backed") is not evidence_backed
                or current["policy_sha256"] != policy_sha256
                or current["policy_version"] != policy_version
                or current["provenance"]["evidence_backed"] is not evidence_backed):
            return unknown("stored_policy_identity_mismatch")
        if identity is not None and current != identity:
            return unknown("mixed_policy_provenance")
        identity = current
        if not isinstance(payload, dict):
            return unknown("frozen_intake_missing")
        try:
            if canonical_sha256(payload) != row.get("payload_sha256"):
                return unknown("frozen_intake_hash_mismatch")
        except (TypeError, ValueError):
            return unknown("invalid_frozen_intake")
        frozen_identity = payload.get("policy_identity")
        frozen_policy = payload.get("paper_policy")
        if (not isinstance(frozen_identity, dict) or not isinstance(frozen_policy, dict)
                or validated_policy_identity({**frozen_identity, "policy_version": frozen_policy.get("policy_version")}) != identity):
            return unknown("frozen_intake_policy_mismatch")
        intake_id = row.get("intake_id")
        if not isinstance(intake_id, str) or not intake_id or intake_id in seen:
            return unknown("duplicate_or_missing_record_identity")
        seen.add(intake_id)
        if not row.get("mint") or row.get("mint") != row.get("intake_mint"):
            return unknown("intake_mint_mismatch")
        if not _safe(record):
            return unknown("unsafe_runtime_record")
        context = payload.get("decision_context")
        if (not isinstance(context, dict) or context.get("mint") != row["mint"]
                or context.get("temporal_cutoff_enforced") is not True
                or context.get("future_evidence_used") is not False):
            return unknown("invalid_frozen_t0_context")
        decided, observed, created, intake_created = map(_time, (
            row.get("decided_at"), row.get("observed_at"), row.get("created_at"), row.get("intake_created_at")))
        if (None in (decided, observed, created, intake_created)
                or decided != _time(context.get("decided_at"))
                or not decided <= observed <= intake_created <= created <= cutoff):
            return unknown("invalid_evidence_chronology")
        evidence_times.append(observed)
        paper = record.get("paper")
        if not isinstance(paper, dict) or paper.get("status") != row.get("paper_status") or not _safe(paper):
            return unknown("invalid_paper_record")
        status = paper["status"]
        if status in ("SIMULATED_OPEN", "SIMULATED_CLOSED"):
            shadow = record.get("shadow")
            adapted_shadow = paper.get("shadow_decision")
            if (record.get("status") != "OBSERVED" or not isinstance(shadow, dict)
                    or shadow.get("policy_version") != policy_version
                    or shadow.get("mint") != row["mint"] or _time(shadow.get("decided_at")) != decided
                    or shadow.get("evidence_snapshot") != context.get("evidence_snapshot")
                    or not isinstance(adapted_shadow, dict)
                    or adapted_shadow.get("source_shadow_decision") != shadow
                    or paper.get("assumptions") != payload.get("execution_assumptions")
                    or paper.get("notional_usd") != payload.get("paper_notional_usd")
                    or paper.get("reference_entry_price") != payload.get("reference_entry_price")):
                return unknown("simulation_frozen_inputs_mismatch")
        if status == "SIMULATED_CLOSED":
            evidence = payload.get("paper_close_evidence")
            if (not isinstance(evidence, dict) or not evidence.get("snapshot_id")
                    or not evidence.get("source") or evidence.get("strictly_later_than_t0") is not True
                    or evidence.get("t0_bundle_recomputed") is not False
                    or _time(evidence.get("captured_at")) != observed or observed <= decided):
                return unknown("invalid_stored_close_chronology")
            horizon_name = frozen_policy.get("horizon")
            horizon = _ALLOWED_HORIZONS.get(horizon_name) if isinstance(horizon_name, str) else None
            if (horizon is None or (observed - decided) < timedelta(seconds=horizon)
                    or paper.get("reference_exit_price") != payload.get("reference_exit_price")):
                return unknown("invalid_frozen_close_horizon_or_price")
            source_key = (row["mint"], decided)
            if source_key in close_sources:
                return unknown("duplicate_closed_simulation")
            close_sources.add(source_key)
            if "policy_identity" in paper and paper["policy_identity"] != identity:
                return unknown("simulation_policy_mismatch")
            adapted = adapt_simulated_execution_for_walk_forward(
                {**paper, "policy_identity": deepcopy(identity)}, closed_at=observed.isoformat(), mint=row["mint"])
            if adapted["status"] != "CLOSED":
                return unknown("ineligible_closed_simulation", missing=adapted["missing"])
            adapted["intake_id"] = intake_id
            closed.append(adapted)
            counts["closed_simulations"] += 1
        elif status == "SIMULATED_OPEN":
            counts["open_simulation_records"] += 1
        elif status == "NOT_SIMULATED":
            counts["not_simulated_records"] += 1
        else:
            return unknown("unknown_simulation_evidence")

    closed.sort(key=lambda item: (_time(item["closed_at"]), item["intake_id"]))
    result.update(status="OBSERVED", counts=counts, selected_policy_identity=identity,
                  provenance_classification="EVIDENCE_BACKED" if evidence_backed else "MANUAL",
                  available_for_walk_forward=len(closed), structurally_eligible=bool(closed),
                  evidence_window={"earliest": min(evidence_times).isoformat(), "latest": max(evidence_times).isoformat()},
                  earliest_closed_record=closed[0]["closed_at"] if closed else None,
                  latest_closed_record=closed[-1]["closed_at"] if closed else None,
                  reasons=[] if closed else ["no_closed_simulations"], truncated=False)
    if release_criteria is not None:
        evaluation = evaluate_walk_forward_paper(closed, release_criteria)
        evaluation["selected_policy_identity"] = deepcopy(identity)
        result["walk_forward"] = evaluation
        result["walk_forward_evaluated"] = evaluation["status"] == "OBSERVED"
        result["reasons"] = evaluation.get("missing", [])
        if result["walk_forward_evaluated"] and produce_artifact:
            from stinky_api.paper_evaluation_artifact import build_evaluation_artifact
            try:
                result["evaluation_artifact"] = build_evaluation_artifact(rows, result, release_criteria)
                result["evaluation_artifact_produced"] = True
            except (TypeError, ValueError, OverflowError):
                return unknown("invalid_evaluation_artifact_content", walk_forward=None,
                               walk_forward_evaluated=False, evaluation_artifact=None,
                               evaluation_artifact_produced=False)
        minimum = release_criteria.get("minimum_closed_trades")
        if type(minimum) is int and minimum > 0:
            result["deficits"] = {"closed_simulations_needed": max(0, minimum - len(closed))}
    return result
