import inspect
from pathlib import Path

import pytest

from stinky_api.prospective_score_calibration_audit import audit_prospective_score_calibration

API_ROOT = Path(__file__).parents[1]


def test_score_calibration_audit_is_temporal_versioned_and_read_only():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert "FROM market_inspections mi" in source
    assert "JOIN entity_launch_outcome_labels ol" in source
    assert "ol.label_version = :label_version" in source
    assert "ol.observed_at > mi.inspected_at" in source
    assert "ol.ingested_at > mi.inspected_at" in source
    assert "ol.ingested_at <= :as_of" in source
    assert "ol.observed_at >= mi.inspected_at" not in source
    assert "mi.model_version = :intelligence_model_version" in source
    assert "mi.evidence->'score'->>'model_version' = :score_model_version" in source
    assert '"intelligence_model_version": intelligence_model' in source
    assert '"score_model_version": score_model' in source
    assert '"runner_precision": precision' in source
    assert '"false_discovery_rate_among_threshold_positives": false_discovery_rate' in source
    assert '"false_positive_rate": false_positive_rate' in source
    assert '"alert_runner_precision": alert_precision' in source
    assert '"alert_false_discovery_rate": alert_false_discovery_rate' in source
    assert '"alert_false_positive_rate": alert_false_positive_rate' in source
    assert '"alert_runner_recall": alert_runner_recall' in source
    assert '"threshold_change_authorized": False' in source
    assert '"trading_authority": False' in source


def test_calibration_uses_one_earliest_decision_per_mint():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert "SELECT DISTINCT ON (mi.mint)" in source
    assert "ORDER BY mi.mint, mi.inspected_at ASC" in source


def test_calibration_configuration_has_no_hidden_defaults():
    params = inspect.signature(audit_prospective_score_calibration).parameters
    for name in (
        "intelligence_model_version", "score_model_version", "outcome_label_version",
        "score_threshold", "as_of", "min_labeled_sample",
    ):
        assert params[name].default is inspect.Parameter.empty


def test_calibration_metric_universes_and_missed_runner_accounting_are_explicit():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert '"score_threshold_metric_universe": "numeric_score"' in source
    assert '"alert_metric_universe": "all_labeled"' in source
    assert '"numeric_score_coverage": len(scored) / labeled if labeled else None' in source
    assert '"unknown_runner_count": len(unknown_runners)' in source
    assert '"unknown_runner_rate": len(unknown_runners) / len(all_runners) if all_runners else None' in source
    assert '"runner_recall": scored_runner_recall' in source
    assert '"missed_runner_count": len(missed_scored_runners)' in source
    assert '"all_labeled_runner_capture_rate": all_labeled_runner_capture' in source
    assert '"alert_missed_runner_count": len(all_runners) - len(alert_runners)' in source


class _NoQuerySession:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid explicit configuration must fail before querying")


@pytest.mark.asyncio
async def test_invalid_explicit_calibration_configuration_fails_closed_before_query():
    result = await audit_prospective_score_calibration(
        _NoQuerySession(),
        intelligence_model_version="intel-v1",
        score_model_version="score-v1",
        outcome_label_version="outcome-v1",
        score_threshold=float("nan"),
        as_of=None,
        min_labeled_sample=0,
    )
    assert result["status"] == "UNKNOWN"
    assert "explicit_timezone_aware_as_of" in result["missing"]
    assert "valid_explicit_score_threshold" in result["missing"]
    assert "valid_explicit_min_labeled_sample" in result["missing"]
    assert result["thresholds_changed"] is False
    assert result["trading_authority"] is False


class _Rows:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
    async def execute(self, *_args, **_kwargs):
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_invalid_scores_are_unknown_and_metric_universes_stay_consistent():
    rows = [
        {"mint": "runner-scored", "label": "RUNNER", "stinky_score": 60.0, "alert_ok": True},
        {"mint": "runner-unknown", "label": "RUNNER", "stinky_score": float("nan"), "alert_ok": False},
        {"mint": "negative", "label": "FADE", "stinky_score": 70.0, "alert_ok": False},
    ]
    result = await audit_prospective_score_calibration(
        _Session(rows),
        intelligence_model_version="intel-v1",
        score_model_version="score-v1",
        outcome_label_version="outcome-v1",
        score_threshold=55,
        as_of="2026-09-30T00:00:00+00:00",
        min_labeled_sample=1,
    )
    assert result["status"] == "OBSERVED"
    assert result["labeled_sample_count"] == 3
    assert result["scored_count"] == 2
    assert result["unknown_score_count"] == 1
    assert result["runner_count"] == 2
    assert result["scored_runner_count"] == 1
    assert result["unknown_runner_count"] == 1
    assert result["runner_recall"] == 1.0
    assert result["missed_runner_count"] == 0
    assert result["all_labeled_runner_capture_rate"] == 0.5
    assert result["false_positive_rate"] == 1.0
