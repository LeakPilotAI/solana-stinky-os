"""Read-only prospective calibration audit for frozen intelligence scores.

Joins decision-time market_inspections to immutable dual-time outcome labels.
It measures historical discrimination only; it never changes score weights,
alert thresholds, policy, or trading authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
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

def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

async def audit_prospective_score_calibration(
    session,
    *,
    intelligence_model_version: str,
    score_model_version: str,
    outcome_label_version: str = "outcome-v1.1.0",
    score_threshold: float = 55.0,
    as_of: datetime | str | None = None,
    min_labeled_sample: int = 20,
) -> dict[str, Any]:
    intelligence_model = str(intelligence_model_version or "").strip()
    score_model = str(score_model_version or "").strip()
    label_version = str(outcome_label_version or "").strip()
    cutoff = _dt(as_of)
    required = max(1, int(min_labeled_sample))
    missing_versions = [
        name for name, value in (
            ("intelligence_model_version", intelligence_model),
            ("score_model_version", score_model),
            ("outcome_label_version", label_version),
        ) if not value
    ]
    if missing_versions:
        return {"status": "UNKNOWN", "missing": missing_versions, **AUTHORITY}

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
         AND ol.observed_at >= mi.inspected_at
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

    records = [dict(r) for r in rows if str(r.get("label") or "") in {"RUNNER", "HELD", "FADE"}]
    labeled = len(records)
    unknown_score = sum(1 for r in records if r.get("stinky_score") is None)
    scored = [r for r in records if r.get("stinky_score") is not None]
    predicted = [r for r in scored if float(r["stinky_score"]) >= float(score_threshold)]
    runners = [r for r in records if r["label"] == "RUNNER"]
    predicted_runners = [r for r in predicted if r["label"] == "RUNNER"]
    false_positives = [r for r in predicted if r["label"] != "RUNNER"]
    negatives = [r for r in scored if r["label"] != "RUNNER"]
    missed_runners = [r for r in scored if float(r["stinky_score"]) < float(score_threshold) and r["label"] == "RUNNER"]

    sufficient = labeled >= required
    precision = len(predicted_runners) / len(predicted) if predicted else None
    false_discovery_rate = len(false_positives) / len(predicted) if predicted else None
    false_positive_rate = len(false_positives) / len(negatives) if negatives else None
    runner_recall = len(predicted_runners) / len(runners) if runners else None

    alert_rows = [r for r in records if r.get("alert_ok") is True]
    alert_runners = [r for r in alert_rows if r["label"] == "RUNNER"]
    alert_false_positives = [r for r in alert_rows if r["label"] != "RUNNER"]
    alert_precision = len(alert_runners) / len(alert_rows) if alert_rows else None
    alert_false_discovery_rate = len(alert_false_positives) / len(alert_rows) if alert_rows else None
    alert_false_positive_rate = len(alert_false_positives) / len([r for r in records if r["label"] != "RUNNER"]) if any(r["label"] != "RUNNER" for r in records) else None
    alert_runner_recall = len(alert_runners) / len(runners) if runners else None

    return {
        "status": "OBSERVED",
        "readiness_status": "CALIBRATION_SAMPLE_SUFFICIENT" if sufficient else "INSUFFICIENT_EVIDENCE",
        "intelligence_model_version": intelligence_model,
        "score_model_version": score_model,
        "outcome_label_version": label_version,
        "as_of": cutoff.isoformat(),
        "score_threshold_audited": float(score_threshold),
        "labeled_sample_count": labeled,
        "minimum_labeled_sample": required,
        "unknown_score_count": unknown_score,
        "unknown_score_rate": unknown_score / labeled if labeled else None,
        "threshold_positive_count": len(predicted),
        "runner_count": len(runners),
        "runner_precision": precision,
        "false_discovery_rate_among_threshold_positives": false_discovery_rate,
        "false_positive_rate": false_positive_rate,
        "runner_recall": runner_recall,
        "missed_runner_count": len(missed_runners),
        "alert_emitted_count": len(alert_rows),
        "alert_frequency": len(alert_rows) / labeled if labeled else None,
        "alert_runner_precision": alert_precision,
        "alert_false_discovery_rate": alert_false_discovery_rate,
        "alert_false_positive_rate": alert_false_positive_rate,
        "alert_runner_recall": alert_runner_recall,
        "threshold_change_authorized": False,
        "missing": [] if sufficient else ["sufficient_labeled_prospective_sample"],
        **AUTHORITY,
    }
