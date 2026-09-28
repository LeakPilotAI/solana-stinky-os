from pathlib import Path
API_ROOT=Path(__file__).parents[1]

def test_score_paper_candidate_is_deterministic_evidence_artifact_only():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_paper_candidate.py").read_text(encoding="utf-8")
    assert 'CANDIDATE_SCHEMA_VERSION = "score-paper-candidate-v1"' in source
    assert '"READY_FOR_PAPER_CANDIDATE_REVIEW"' in source
    assert 'evaluation.get("candidate_selection")!="TRAINING_ONLY"' in source
    assert '"intelligence_model_version"' in source
    assert '"score_model_version"' in source
    assert '"outcome_label_version"' in source
    assert '"training_window":training' in source
    assert '"holdout_window":holdout' in source
    assert '"holdout_metrics":metrics' in source
    assert '"readiness_criteria":criteria' in source
    assert 'hashlib.sha256(canonical.encode("utf-8")).hexdigest()' in source
    assert '"requires_separate_policy_provisioning":True' in source
    assert '"requires_explicit_activation":True' in source
    assert '"policy_provisioning_authority": False' in source
    assert '"automatic_activation": False' in source
    assert '"trading_authority": False' in source

def test_candidate_requires_readiness_to_match_frozen_evaluation():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_paper_candidate.py").read_text(encoding="utf-8")
    assert '"readiness_selected_threshold_match"' in source
    assert '"readiness_holdout_evidence_match"' in source
    assert 'readiness.get(key)!=evaluation.get(key)' in source
    assert 'all(v is True for v in checks.values())' in source
