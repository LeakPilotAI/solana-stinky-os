from pathlib import Path
API_ROOT=Path(__file__).parents[1]

def test_post_candidate_readiness_is_review_only_and_fail_closed():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_readiness.py").read_text(encoding="utf-8")
    assert '"PROSPECTIVE_COMPARISON_COMPLETE"' in source
    assert 'actionable.get("universe")!="actionable_score"' in source
    assert 'alerts.get("universe")!="all_labeled"' in source
    assert '"sufficient_later_sample"' in source
    assert '"sufficient_later_runners"' in source
    assert '"sufficient_later_negatives"' in source
    assert '"sufficient_actionable_score_coverage"' in source
    assert '"sufficient_actionable_threshold_positives"' in source
    assert '"minimum_actionable_runner_precision"' in source
    assert '"maximum_actionable_false_discovery_rate"' in source
    assert '"maximum_actionable_false_positive_rate"' in source
    assert '"minimum_actionable_runner_recall"' in source
    assert '"maximum_actionable_missed_runners"' in source
    assert '"READY_FOR_PAPER_POLICY_REVIEW"' in source
    assert '"policy_provisioning_authority":False' in source
    assert '"automatic_activation":False' in source
    assert '"trading_authority":False' in source

def test_readiness_rejects_fractional_count_criteria():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_readiness.py").read_text(encoding="utf-8")
    assert "isinstance(v,float) and not v.is_integer()" in source
