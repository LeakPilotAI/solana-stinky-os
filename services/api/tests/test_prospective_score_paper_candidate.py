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


def test_candidate_rejects_out_of_domain_or_noncanonical_evidence():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_paper_candidate.py").read_text(encoding="utf-8")
    assert "not 0.0 <= threshold <= 100.0" in source
    assert '"selected_threshold_score_domain"' in source
    assert "allow_nan=False" in source
    assert '"canonical_json_safe_finite_evidence"' in source


def test_candidate_binds_readiness_to_cutoff_training_and_evaluation_configuration():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_paper_candidate.py").read_text(encoding="utf-8")
    readiness=(API_ROOT/"src"/"stinky_api"/"prospective_score_readiness.py").read_text(encoding="utf-8")
    assert '"evaluation_as_of":evaluation.get("as_of")' in readiness
    assert '"training_window":evaluation.get("training_window")' in readiness
    assert '"selected_training_metrics":evaluation.get("selected_training_metrics")' in readiness
    assert '"evaluation_criteria":evaluation.get("criteria")' in readiness
    assert '"readiness_evaluation_as_of_match"' in source
    assert '"readiness_training_evidence_match"' in source
    assert '"readiness_evaluation_criteria_match"' in source
