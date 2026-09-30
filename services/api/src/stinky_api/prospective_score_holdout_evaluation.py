"""Chronological held-out evaluation for frozen prospective score thresholds.

Candidate selection uses only the earlier training window. The chosen threshold
is then frozen and evaluated on the later holdout. Descriptive evidence only:
never mutates live thresholds, score weights, alert policy, or trading authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math
from sqlalchemy import text

AUTHORITY = {
    "interpretation": "HELD_OUT_SCORE_THRESHOLD_EVALUATION",
    "read_only": True,
    "evidence_only": True,
    "candidate_selection": "TRAINING_ONLY",
    "live_threshold_changed": False,
    "score_weights_changed": False,
    "trading_authority": False,
    "live_execution": False,
}

def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw: return None
    try: parsed = datetime.fromisoformat(raw)
    except ValueError: return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value,bool): return None
    if isinstance(value,float) and not value.is_integer(): return None
    try: n=int(value)
    except (TypeError,ValueError): return None
    return n if n>=1 else None

def _prob(value: Any) -> float | None:
    if value is None or isinstance(value,bool): return None
    try: n=float(value)
    except (TypeError,ValueError): return None
    return n if math.isfinite(n) and 0.0<=n<=1.0 else None

def _metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    scored = [r for r in rows if r.get("stinky_score") is not None]
    runners = [r for r in scored if r["label"] == "RUNNER"]
    negatives = [r for r in scored if r["label"] != "RUNNER"]
    positive = [r for r in scored if float(r["stinky_score"]) >= threshold]
    tp = [r for r in positive if r["label"] == "RUNNER"]
    fp = [r for r in positive if r["label"] != "RUNNER"]
    return {
        "sample_count": len(rows),
        "scored_count": len(scored),
        "unknown_score_count": len(rows) - len(scored),
        "unknown_score_rate": (len(rows) - len(scored)) / len(rows) if rows else None,
        "threshold_positive_count": len(positive),
        "runner_count": len(runners),
        "runner_precision": len(tp) / len(positive) if positive else None,
        "false_discovery_rate": len(fp) / len(positive) if positive else None,
        "false_positive_rate": len(fp) / len(negatives) if negatives else None,
        "runner_recall": len(tp) / len(runners) if runners else None,
        "missed_runner_count": len(runners) - len(tp),
    }

async def evaluate_score_threshold_out_of_sample(
    session,
    *,
    intelligence_model_version: str,
    score_model_version: str,
    outcome_label_version: str,
    candidate_thresholds: tuple[float, ...],
    evaluation_fraction: float,
    min_training_sample: int,
    min_holdout_sample: int,
    min_training_runners: int,
    min_training_negatives: int,
    min_holdout_runners: int,
    min_holdout_negatives: int,
    min_training_runner_precision: float,
    as_of: datetime | str,
) -> dict[str, Any]:
    intel = str(intelligence_model_version or "").strip()
    score_model = str(score_model_version or "").strip()
    label_version = str(outcome_label_version or "").strip()
    cutoff = _dt(as_of)
    try:
        thresholds = sorted({float(x) for x in candidate_thresholds})
    except (TypeError,ValueError):
        thresholds = []
    fraction = _prob(evaluation_fraction)
    precision_floor = _prob(min_training_runner_precision)
    counts=[_positive_int(x) for x in (min_training_sample,min_holdout_sample,min_training_runners,min_training_negatives,min_holdout_runners,min_holdout_negatives)]
    if (
        not intel or not score_model or not label_version or cutoff is None
        or not thresholds or any(not math.isfinite(x) or not 0.0<=x<=100.0 for x in thresholds)
        or fraction is None or not 0.10<=fraction<=0.50 or precision_floor is None
        or any(x is None for x in counts)
    ):
        return {"status": "UNKNOWN", "evaluation_status": "NOT_EVALUATION_READY", "missing": ["valid_explicit_evaluation_configuration"], **AUTHORITY}
    min_train,min_holdout,min_train_runners,min_train_negatives,min_test_runners,min_test_negatives=counts

    rows = (await session.execute(text("""
        SELECT DISTINCT ON (mi.mint)
          mi.mint, mi.inspected_at, mi.stinky_score, mi.alert_ok,
          ol.label, ol.observed_at AS outcome_observed_at, ol.ingested_at AS outcome_ingested_at
        FROM market_inspections mi
        JOIN entity_launch_outcome_labels ol
          ON ol.mint = mi.mint
         AND ol.label_version = :label_version
         AND ol.observed_at > mi.inspected_at
         AND ol.ingested_at > mi.inspected_at
         AND ol.ingested_at <= :as_of
        WHERE mi.model_version = :intelligence_model_version
          AND mi.evidence->'score'->>'model_version' = :score_model_version
          AND mi.inspected_at <= :as_of
        ORDER BY mi.mint, mi.inspected_at ASC, ol.observed_at ASC, ol.ingested_at ASC
    """), {
        "intelligence_model_version": intel,
        "score_model_version": score_model,
        "label_version": label_version,
        "as_of": cutoff,
    })).mappings().all()
    records = [dict(r) for r in rows if str(r.get("label") or "") in {"RUNNER", "HELD", "FADE"}]
    records.sort(key=lambda r: _dt(r["inspected_at"]) or datetime.max.replace(tzinfo=timezone.utc))

    total = len(records)
    holdout_count = max(min_holdout, int(round(total * fraction))) if total else 0
    train_count = total - holdout_count
    criteria = {
        "evaluation_fraction": fraction,
        "min_training_sample": min_train,
        "min_holdout_sample": min_holdout,
        "min_training_runners": min_train_runners,
        "min_training_negatives": min_train_negatives,
        "min_holdout_runners": min_test_runners,
        "min_holdout_negatives": min_test_negatives,
        "min_training_runner_precision": precision_floor,
        "candidate_thresholds": thresholds,
    }
    if train_count < min_train or holdout_count < min_holdout:
        return {
            "status": "OBSERVED",
            "evaluation_status": "NOT_EVALUATION_READY",
            "training_sample_count": max(train_count, 0),
            "holdout_sample_count": max(holdout_count, 0),
            "criteria": criteria,
            "missing": ["sufficient_chronological_train_holdout_sample"],
            **AUTHORITY,
        }

    training = records[:train_count]
    holdout = records[train_count:]
    training_runner_count = sum(1 for r in training if r["label"] == "RUNNER")
    training_negative_count = sum(1 for r in training if r["label"] != "RUNNER")
    holdout_runner_count = sum(1 for r in holdout if r["label"] == "RUNNER")
    holdout_negative_count = sum(1 for r in holdout if r["label"] != "RUNNER")
    class_missing = []
    if training_runner_count < min_train_runners:
        class_missing.append("sufficient_training_runners")
    if training_negative_count < min_train_negatives:
        class_missing.append("sufficient_training_negatives")
    if holdout_runner_count < min_test_runners:
        class_missing.append("sufficient_holdout_runners")
    if holdout_negative_count < min_test_negatives:
        class_missing.append("sufficient_holdout_negatives")
    if class_missing:
        return {
            "status": "OBSERVED",
            "evaluation_status": "NOT_EVALUATION_READY",
            "training_sample_count": len(training),
            "holdout_sample_count": len(holdout),
            "training_runner_count": training_runner_count,
            "training_negative_count": training_negative_count,
            "holdout_runner_count": holdout_runner_count,
            "holdout_negative_count": holdout_negative_count,
            "criteria": criteria,
            "missing": class_missing,
            **AUTHORITY,
        }

    training_candidates = []
    for threshold in thresholds:
        metrics = _metrics(training, threshold)
        training_candidates.append({"threshold": threshold, **metrics})

    eligible = [
        item for item in training_candidates
        if item["runner_precision"] is not None
        and item["runner_precision"] >= precision_floor
        and item["threshold_positive_count"] > 0
    ]
    if not eligible:
        return {
            "status": "OBSERVED",
            "evaluation_status": "NO_TRAINING_CANDIDATE",
            "training_sample_count": len(training),
            "holdout_sample_count": len(holdout),
            "training_candidates": training_candidates,
            "criteria": criteria,
            "missing": ["training_threshold_meeting_precision_floor"],
            **AUTHORITY,
        }

    # Selection is training-only: maximize recall after satisfying the precision floor,
    # then precision, then prefer the higher threshold on exact ties.
    selected = max(
        eligible,
        key=lambda item: (
            item["runner_recall"] if item["runner_recall"] is not None else -1.0,
            item["runner_precision"],
            item["threshold"],
        ),
    )
    threshold = float(selected["threshold"])
    holdout_metrics = _metrics(holdout, threshold)
    return {
        "status": "OBSERVED",
        "evaluation_status": "HELD_OUT_EVALUATED",
        "intelligence_model_version": intel,
        "score_model_version": score_model,
        "outcome_label_version": label_version,
        "as_of": cutoff.isoformat(),
        "training_window": {
            "sample_count": len(training),
            "runner_count": training_runner_count,
            "negative_count": training_negative_count,
            "first_inspected_at": _dt(training[0]["inspected_at"]).isoformat(),
            "last_inspected_at": _dt(training[-1]["inspected_at"]).isoformat(),
        },
        "holdout_window": {
            "sample_count": len(holdout),
            "runner_count": holdout_runner_count,
            "negative_count": holdout_negative_count,
            "first_inspected_at": _dt(holdout[0]["inspected_at"]).isoformat(),
            "last_inspected_at": _dt(holdout[-1]["inspected_at"]).isoformat(),
        },
        "selected_threshold": threshold,
        "selection_basis": "training_only_precision_floor_then_max_runner_recall",
        "selected_training_metrics": selected,
        "holdout_metrics": holdout_metrics,
        "training_candidates": training_candidates,
        "criteria": criteria,
        "threshold_change_authorized": False,
        "missing": [],
        **AUTHORITY,
    }
