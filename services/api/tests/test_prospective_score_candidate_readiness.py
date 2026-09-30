from pathlib import Path

from stinky_api.paper_evidence_json import content_sha256
from stinky_api.prospective_score_candidate_readiness import assess_post_candidate_readiness

API_ROOT=Path(__file__).parents[1]


def _comparison():
    return {
        "status":"OBSERVED",
        "comparison_status":"PROSPECTIVE_COMPARISON_COMPLETE",
        "candidate_version":"score-paper-candidate-v1:" + "a"*16,
        "evidence_sha256":"a"*64,
        "candidate_threshold":55.0,
        "candidate_cutoff":"2026-09-29T00:00:00+00:00",
        "as_of":"2026-09-30T00:00:00+00:00",
        "sample_count":10,
        "runner_count":3,
        "negative_count":7,
        "unknown_score_count":1,
        "unknown_score_rate":0.1,
        "actionable_score_count":9,
        "actionable_score_rate":0.9,
        "non_actionable_numeric_score_count":0,
        "non_actionable_numeric_score_rate":0.0,
        "score_threshold_metrics":{
            "universe":"numeric_score","eligible_count":9,"runner_count":3,"negative_count":6,
            "positive_count":4,"runner_precision":0.75,"false_discovery_rate":0.25,
            "false_positive_rate":1/6,"runner_recall":1.0,"missed_runner_count":0,
        },
        "actionable_score_threshold_metrics":{
            "universe":"actionable_score","eligible_count":9,"runner_count":3,"negative_count":6,
            "positive_count":4,"runner_precision":0.75,"false_discovery_rate":0.25,
            "false_positive_rate":1/6,"runner_recall":1.0,"missed_runner_count":0,
        },
        "actual_alert_admission_metrics":{
            "universe":"all_labeled","eligible_count":10,"runner_count":3,"negative_count":7,
            "positive_count":3,"runner_precision":2/3,"false_discovery_rate":1/3,
            "false_positive_rate":1/7,"runner_recall":2/3,"missed_runner_count":1,
        },
        "missing":[],
    }


def _criteria():
    return {
        "min_later_sample":10,
        "min_later_runners":3,
        "min_later_negatives":7,
        "min_actionable_score_rate":0.8,
        "min_actionable_positive_count":4,
        "min_actionable_runner_precision":0.7,
        "max_actionable_false_discovery_rate":0.3,
        "max_actionable_false_positive_rate":0.2,
        "min_actionable_runner_recall":0.9,
        "max_actionable_missed_runners":0,
    }


def test_post_candidate_readiness_is_review_only_and_fail_closed():
    source=(API_ROOT/"src"/"stinky_api"/"prospective_score_candidate_readiness.py").read_text(encoding="utf-8")
    assert '"PROSPECTIVE_COMPARISON_COMPLETE"' in source
    assert 'actionable.get("universe")!="actionable_score"' in source
    assert 'alerts.get("universe")!="all_labeled"' in source
    assert 'score_metrics.get("universe")!="numeric_score"' in source
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


def test_readiness_preserves_and_content_addresses_exact_comparison_evidence():
    comparison=_comparison()
    result=assess_post_candidate_readiness(comparison, **_criteria())
    assert result["readiness_status"]=="READY_FOR_PAPER_POLICY_REVIEW"
    assert result["comparison_evidence"]==comparison
    assert result["comparison_evidence"] is not comparison
    assert result["comparison_evidence_sha256"]==content_sha256(comparison)
    assert result["unknown_score_rate"]==0.1
    assert result["actionable_score_rate"]==0.9
    assert result["score_threshold_metrics"]["universe"]=="numeric_score"
    actionable=result["actionable_score_threshold_metrics"]
    assert actionable["runner_precision"]==0.75
    assert actionable["false_discovery_rate"]==0.25
    assert actionable["false_positive_rate"]==1/6
    assert actionable["runner_recall"]==1.0
    assert actionable["missed_runner_count"]==0
    comparison["actionable_score_threshold_metrics"]["runner_precision"]=0.0
    assert result["comparison_evidence"]["actionable_score_threshold_metrics"]["runner_precision"]==0.75


def test_noncanonical_comparison_evidence_fails_closed():
    comparison=_comparison()
    comparison["noncanonical"]=object()
    result=assess_post_candidate_readiness(comparison, **_criteria())
    assert result["status"]=="UNKNOWN"
    assert result["readiness_status"]=="NOT_READY"
    assert result["missing"]==["canonical_post_candidate_comparison_evidence"]
