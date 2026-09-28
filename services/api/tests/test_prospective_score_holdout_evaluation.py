from pathlib import Path

API_ROOT = Path(__file__).parents[1]

def test_holdout_threshold_selection_is_chronological_training_only():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_holdout_evaluation.py").read_text(encoding="utf-8")
    assert "SELECT DISTINCT ON (mi.mint)" in source
    assert "ORDER BY mi.mint, mi.inspected_at ASC" in source
    assert "records.sort(key=lambda r: _dt(r[\"inspected_at\"]))" in source
    assert "training = records[:train_count]" in source
    assert "holdout = records[train_count:]" in source
    assert "training_candidates.append" in source
    assert "_metrics(holdout, threshold)" in source
    assert '"candidate_selection": "TRAINING_ONLY"' in source
    assert '"threshold_change_authorized": False' in source

def test_holdout_reports_correct_discrimination_metrics_and_versions():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_holdout_evaluation.py").read_text(encoding="utf-8")
    assert "mi.model_version = :intelligence_model_version" in source
    assert "mi.evidence->'score'->>'model_version' = :score_model_version" in source
    assert "ol.label_version = :label_version" in source
    assert "ol.ingested_at <= :as_of" in source
    assert '"runner_precision"' in source
    assert '"false_discovery_rate"' in source
    assert '"false_positive_rate"' in source
    assert '"runner_recall"' in source
    assert '"unknown_score_rate"' in source
    assert '"trading_authority": False' in source
