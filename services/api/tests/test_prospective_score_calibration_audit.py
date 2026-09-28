from pathlib import Path

API_ROOT = Path(__file__).parents[1]

def test_score_calibration_audit_is_temporal_versioned_and_read_only():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert "FROM market_inspections mi" in source
    assert "JOIN entity_launch_outcome_labels ol" in source
    assert "ol.label_version = :label_version" in source
    assert "ol.observed_at >= mi.inspected_at" in source
    assert "ol.ingested_at <= :as_of" in source
    assert "mi.model_version = :intelligence_model_version" in source
    assert "mi.evidence->'score'->>'model_version' = :score_model_version" in source
    assert '"intelligence_model_version": intelligence_model' in source
    assert '"score_model_version": score_model' in source
    assert '"runner_precision": precision' in source
    assert '"false_discovery_rate_among_threshold_positives": false_discovery_rate' in source
    assert '"false_positive_rate": false_positive_rate' in source
    assert 'len(false_positives) / len(negatives)' in source
    assert '"alert_runner_precision": alert_precision' in source
    assert '"alert_false_discovery_rate": alert_false_discovery_rate' in source
    assert '"alert_false_positive_rate": alert_false_positive_rate' in source
    assert '"alert_runner_recall": alert_runner_recall' in source
    assert '"runner_recall": runner_recall' in source
    assert '"unknown_score_rate": unknown_score / labeled if labeled else None' in source
    assert '"alert_frequency": len(alert_rows) / labeled if labeled else None' in source
    assert '"threshold_change_authorized": False' in source
    assert '"trading_authority": False' in source


def test_calibration_uses_one_earliest_decision_per_mint():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert "SELECT DISTINCT ON (mi.mint)" in source
    assert "ORDER BY mi.mint, mi.inspected_at ASC" in source
