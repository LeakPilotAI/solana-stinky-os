"""Read-only prospective calibration audit for frozen intelligence scores.

Joins decision-time market_inspections to immutable dual-time outcome labels.
It measures historical discrimination only; it never changes score weights,
alert thresholds, policy, or trading authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any
from sqlalchemy import text

AUTHORITY = {
    "interpretation": "PROSPECTIVE_SCORE_CALIBRATION_AUDIT",
    "read_only": True,
    "evidence_only": True,
    "thresholds_changed": False,
    "predictive_authority": False,
    "trading_authority": False,
    "trade_signal": False,
    "live_execution": False,
}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 1 else None


def _threshold(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and 0.0 <= result <= 100.0 else None


async def audit_prospective_score_calibration(
    session,
    *,
    intelligence_model_version: str,
    score_model_version: str,
    outcome_label_version: str,
    score_threshold: float,
    as_of: datetime | str,
    min_labeled_sample: int,
) -> dict[str, Any]:
    """Audit one explicit frozen score threshold against later-known outcomes.

    Every configuration value is caller supplied. Outcome evidence must be both
    observed and ingested strictly after the inspected decision and ingested no
    later than the explicit as_of cutoff.
    """
    intelligence_model = str(intelligence_model_version or "").strip()
    score_model = str(score_model_version or "").strip()
    label_version = str(outcome_label_version or "").strip()
    cutoff = _dt(as_of)
    threshold = _threshold(score_threshold)
    required = _positive_int(min_labeled_sample)
    missing = [
        name for name, value in (
            ("intelligence_model_version", intelligence_model),
            ("score_model_version", score_model),
            ("outcome_label_version", label_version),
        ) if not value
    ]
    if cutoff is None:
        missing.append("explicit_timezone_aware_as_of")
    if threshold is None:
        missing.append("valid_explicit_score_threshold")
    if required is None:
        missing.append("valid_explicit_min_labeled_sample")
    if missing:
        return {"status": "UNKNOWN", "missing": missing, **AUTHORITY}

    rows = (await session.execute(text("""
        SELECT DISTINCT ON (mi.mint)
          mi.mint, mi.inspected_at,
          mi.model_version AS intelligence_model_version,
          mi.evidence->'score'->>'model_version' AS score_model_version,
          mi.stinky_score, mi.score_confidence, mi.alert_ok, mi.alert_reason,
          ol.label, ol.label_version, ol.observed_at AS outcome_observed_at,
          ol.ingested_at AS outcome_ingested_at
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
        "intelligence_model_version": intelligence_model,
        "score_model_version": score_model,
        "label_version": label_version,
        "as_of": cutoff,
    })).mappings().all()

    records = []
    for raw in rows:
        record = dict(raw)
        if str(record.get("label") or "") not in {"RUNNER", "HELD", "FADE"}:
            continue
        value = record.get("stinky_score")
        normalized_score = None
        if value is not None and not isinstance(value, bool):
            try:
                candidate = float(value)
                if math.isfinite(candidate) and 0.0 <= candidate <= 100.0:
                    normalized_score = candidate
            except (TypeError, ValueError, OverflowError):
                pass
        record["stinky_score"] = normalized_score
        records.append(record)
    labeled = len(records)
    scored = [r for r in records if r.get("stinky_score") is not None]
    unknown = [r for r in records if r.get("stinky_score") is None]
    scored_runners = [r for r in scored if r["label"] == "RUNNER"]
    scored_negatives = [r for r in scored if r["label"] != "RUNNER"]
    all_runners = [r for r in records if r["label"] == "RUNNER"]
    unknown_runners = [r for r in unknown if r["label"] == "RUNNER"]

    predicted = [r for r in scored if float(r["stinky_score"]) >= threshold]
    predicted_runners = [r for r in predicted if r["label"] == "RUNNER"]
    false_positives = [r for r in predicted if r["label"] != "RUNNER"]
    missed_scored_runners = [r for r in scored_runners if float(r["stinky_score"]) < threshold]

    sufficient = labeled >= required
    precision = len(predicted_runners) / len(predicted) if predicted else None
    false_discovery_rate = len(false_positives) / len(predicted) if predicted else None
    false_positive_rate = len(false_positives) / len(scored_negatives) if scored_negatives else None
    scored_runner_recall = len(predicted_runners) / len(scored_runners) if scored_runners else None
    all_labeled_runner_capture = len(predicted_runners) / len(all_runners) if all_runners else None

    alert_rows = [r for r in records if r.get("alert_ok") is True]
    alert_runners = [r for r in alert_rows if r["label"] == "RUNNER"]
    alert_false_positives = [r for r in alert_rows if r["label"] != "RUNNER"]
    all_negatives = [r for r in records if r["label"] != "RUNNER"]
    alert_precision = len(alert_runners) / len(alert_rows) if alert_rows else None
    alert_false_discovery_rate = len(alert_false_positives) / len(alert_rows) if alert_rows else None
    alert_false_positive_rate = len(alert_false_positives) / len(all_negatives) if all_negatives else None
    alert_runner_recall = len(alert_runners) / len(all_runners) if all_runners else None

    return {
        "status": "OBSERVED",
        "readiness_status": "CALIBRATION_SAMPLE_SUFFICIENT" if sufficient else "INSUFFICIENT_EVIDENCE",
        "intelligence_model_version": intelligence_model,
        "score_model_version": score_model,
        "outcome_label_version": label_version,
        "as_of": cutoff.isoformat(),
        "score_threshold_audited": threshold,
        "minimum_labeled_sample": required,
        "labeled_sample_count": labeled,
        "scored_count": len(scored),
        "numeric_score_coverage": len(scored) / labeled if labeled else None,
        "unknown_score_count": len(unknown),
        "unknown_score_rate": len(unknown) / labeled if labeled else None,
        "runner_count": len(all_runners),
        "runner_count_all_labeled": len(all_runners),
        "unknown_runner_count": len(unknown_runners),
        "unknown_runner_rate": len(unknown_runners) / len(all_runners) if all_runners else None,
        "score_threshold_metric_universe": "numeric_score",
        "threshold_positive_count": len(predicted),
        "scored_runner_count": len(scored_runners),
        "runner_precision": precision,
        "false_discovery_rate_among_threshold_positives": false_discovery_rate,
        "false_positive_rate": false_positive_rate,
        "runner_recall": scored_runner_recall,
        "missed_runner_count": len(missed_scored_runners),
        "all_labeled_runner_capture_rate": all_labeled_runner_capture,
        "alert_metric_universe": "all_labeled",
        "alert_emitted_count": len(alert_rows),
        "alert_frequency": len(alert_rows) / labeled if labeled else None,
        "alert_runner_precision": alert_precision,
        "alert_false_discovery_rate": alert_false_discovery_rate,
        "alert_false_positive_rate": alert_false_positive_rate,
        "alert_runner_recall": alert_runner_recall,
        "alert_missed_runner_count": len(all_runners) - len(alert_runners),
        "threshold_change_authorized": False,
        "missing": [] if sufficient else ["sufficient_labeled_prospective_sample"],
        **AUTHORITY,
    }
