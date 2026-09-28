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


def test_holdout_requires_runner_and_negative_support_in_both_windows():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_holdout_evaluation.py").read_text(encoding="utf-8")
    assert '"sufficient_training_runners"' in source
    assert '"sufficient_training_negatives"' in source
    assert '"sufficient_holdout_runners"' in source
    assert '"sufficient_holdout_negatives"' in source
    assert '"training_runner_count": training_runner_count' in source
    assert '"training_negative_count": training_negative_count' in source
    assert '"holdout_runner_count": holdout_runner_count' in source
    assert '"holdout_negative_count": holdout_negative_count' in source
    assert '"evaluation_status": "NOT_EVALUATION_READY"' in source
