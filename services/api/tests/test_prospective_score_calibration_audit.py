from pathlib import Path

API_ROOT = Path(__file__).parents[1]

def test_score_calibration_audit_is_temporal_versioned_and_read_only():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_calibration_audit.py").read_text(encoding="utf-8")
    assert "FROM market_inspections mi" in source
    assert "JOIN entity_launch_outcome_labels ol" in source
    assert "ol.label_version = :label_version" in source
    assert "ol.observed_at >= mi.inspected_at" in source
    assert "ol.ingested_at <= :as_of" in source
    assert "mi.model_version = :model_version" in source
    assert '"runner_precision": precision' in source
    assert '"false_positive_rate_among_threshold_positives": false_positive_rate' in source
    assert '"runner_recall": runner_recall' in source
    assert '"unknown_score_rate": unknown_score / labeled if labeled else None' in source
    assert '"alert_frequency": len(alert_rows) / labeled if labeled else None' in source
    assert '"threshold_change_authorized": False' in source
    assert '"trading_authority": False' in source
