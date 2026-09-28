from pathlib import Path
API_ROOT=Path(__file__).parents[1]

def test_score_readiness_is_evidence_only_and_requires_held_out_metrics():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_readiness.py").read_text(encoding="utf-8")
    assert 'evaluation.get("evaluation_status")!="HELD_OUT_EVALUATED"' in source
    assert 'evaluation.get("candidate_selection")!="TRAINING_ONLY"' in source
    assert '"sufficient_holdout_sample"' in source
    assert '"sufficient_holdout_runners"' in source
    assert '"sufficient_holdout_negatives"' in source
    assert '"acceptable_unknown_score_rate"' in source
    assert '"minimum_runner_precision"' in source
    assert '"maximum_false_discovery_rate"' in source
    assert '"maximum_false_positive_rate"' in source
    assert '"minimum_runner_recall"' in source
    assert '"maximum_missed_runners"' in source
    assert '"READY_FOR_PAPER_CANDIDATE_REVIEW"' in source
    assert '"requires_separate_versioned_paper_policy_provisioning": True' in source
    assert '"policy_provisioning_authority": False' in source
    assert '"automatic_activation": False' in source
    assert '"trading_authority": False' in source
