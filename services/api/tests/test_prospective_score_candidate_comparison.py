from pathlib import Path
API_ROOT=Path(__file__).parents[1]

def test_candidate_comparison_is_strictly_post_evidence_and_version_pinned():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_comparison.py").read_text(encoding="utf-8")
    assert "mi.inspected_at>:candidate_cutoff" in source
    assert "mi.inspected_at<=:as_of" in source
    assert "ol.observed_at>mi.inspected_at" in source
    assert "ol.ingested_at>mi.inspected_at" in source
    assert "ol.ingested_at<=:as_of" in source
    assert "ol.observed_at>=mi.inspected_at" not in source
    assert "mi.model_version=:intelligence_model_version" in source
    assert "mi.evidence->'score'->>'model_version'=:score_model_version" in source
    assert "ol.label_version=:label_version" in source
    assert "SELECT DISTINCT ON (mi.mint)" in source
    assert "ORDER BY mi.mint, mi.inspected_at ASC" in source

def test_candidate_comparison_separates_score_and_actual_alert_admission():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_comparison.py").read_text(encoding="utf-8")
    assert '"candidate_positive"' in source
    assert '"actual_alert_positive"' in source
    assert '"score_threshold_metrics"' in source
    assert '"actual_alert_admission_metrics"' in source
    assert '"unknown_score_rate"' in source
    assert '"sufficient_later_sample"' in source
    assert '"sufficient_later_runners"' in source
    assert '"sufficient_later_negatives"' in source
    assert '"candidate_activation":False' in source
    assert '"policy_provisioning_authority":False' in source
    assert '"trading_authority":False' in source


def test_comparison_verifies_candidate_identity_and_exposes_actionability():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_comparison.py").read_text(encoding="utf-8")
    assert "hashlib.sha256(canonical.encode" in source
    assert '"candidate_identity_mismatch"' in source
    assert "allow_nan=False" in source
    assert "evidence->'score'->>'actionable'" in source
    assert "evidence->'score'->>'interpretation'" in source
    assert '"actionable_score_count"' in source
    assert '"non_actionable_numeric_score_count"' in source
    assert '"actionable_score_threshold_metrics"' in source


def test_comparison_uses_explicit_metric_universes():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_comparison.py").read_text(encoding="utf-8")
    assert 'universe=="numeric_score"' in source
    assert 'universe=="actionable_score"' in source
    assert 'universe=="all_labeled"' in source
    assert '_metrics(records,"candidate_positive",universe="numeric_score")' in source
    assert '_metrics(records,"actionable_candidate_positive",universe="actionable_score")' in source
    assert '_metrics(records,"actual_alert_positive",universe="all_labeled")' in source
    assert '"eligible_count":len(eligible)' in source


def test_comparison_criteria_fail_closed_without_integer_truncation():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_comparison.py").read_text(encoding="utf-8")
    assert "isinstance(v,float) and not v.is_integer()" in source
    assert '"valid_explicit_comparison_criteria"' in source
    assert "required_counts=[_positive_count(x)" in source
    assert "max(1,int(min_sample))" not in source


def test_comparison_has_no_hidden_evidence_sufficiency_defaults():
    import inspect
    from stinky_api.prospective_score_candidate_comparison import compare_score_paper_candidate

    params = inspect.signature(compare_score_paper_candidate).parameters
    for name in ("min_sample", "min_runners", "min_negatives"):
        assert params[name].default is inspect.Parameter.empty
