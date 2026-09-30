from pathlib import Path

API_ROOT = Path(__file__).parents[1]

def test_holdout_threshold_selection_is_chronological_training_only():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_score_holdout_evaluation.py").read_text(encoding="utf-8")
    assert "SELECT DISTINCT ON (mi.mint)" in source
    assert "ORDER BY mi.mint, mi.inspected_at ASC" in source
    assert "records.sort(key=lambda r: _dt(r[" in source
    assert "datetime.max.replace(tzinfo=timezone.utc)" in source
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
    assert "ol.observed_at > mi.inspected_at" in source
    assert "ol.ingested_at > mi.inspected_at" in source
    assert "ol.ingested_at <= :as_of" in source
    assert "ol.observed_at >= mi.inspected_at" not in source
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


def test_holdout_configuration_fails_closed_instead_of_clamping_or_defaulting_now():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_holdout_evaluation.py").read_text(encoding="utf-8")
    assert '"valid_explicit_evaluation_configuration"' in source
    assert "cutoff is None" in source
    assert "not 0.10<=fraction<=0.50" in source
    assert "not 0.0<=x<=100.0" in source
    assert "isinstance(value,float) and not value.is_integer()" in source
    assert "datetime.now(timezone.utc)" not in source
    assert "min(max(float(evaluation_fraction)" not in source


def test_holdout_evaluation_has_no_hidden_configuration_defaults():
    import inspect
    from stinky_api.prospective_score_holdout_evaluation import evaluate_score_threshold_out_of_sample

    params = inspect.signature(evaluate_score_threshold_out_of_sample).parameters
    required = (
        "outcome_label_version", "candidate_thresholds", "evaluation_fraction",
        "min_training_sample", "min_holdout_sample", "min_training_runners",
        "min_training_negatives", "min_holdout_runners", "min_holdout_negatives",
        "min_training_runner_precision", "as_of",
    )
    for name in required:
        assert params[name].default is inspect.Parameter.empty
