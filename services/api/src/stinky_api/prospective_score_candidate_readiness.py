"""Evidence-only readiness gate for a post-candidate prospective comparison.

Passing means only that the frozen paper candidate has enough later evidence for
operator paper-policy review. This module cannot provision or activate policy.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from stinky_api.paper_evidence_json import content_sha256

AUTHORITY={
    "interpretation":"POST_CANDIDATE_EVIDENCE_READINESS",
    "paper_only":True,"read_only":True,"evidence_only":True,
    "policy_provisioning_authority":False,"automatic_activation":False,
    "live_threshold_changed":False,"trading_authority":False,"live_execution":False,
}

def _prob(v:Any)->float|None:
    if v is None or isinstance(v,bool): return None
    try: n=float(v)
    except (TypeError,ValueError): return None
    return n if math.isfinite(n) and 0.0<=n<=1.0 else None

def _count(v:Any)->int|None:
    if v is None or isinstance(v,bool): return None
    if isinstance(v,float) and not v.is_integer(): return None
    try: n=int(v)
    except (TypeError,ValueError): return None
    return n if n>=0 else None

def assess_post_candidate_readiness(
    comparison:dict[str,Any], *,
    min_later_sample:int,min_later_runners:int,min_later_negatives:int,
    min_actionable_score_rate:float,min_actionable_positive_count:int,
    min_actionable_runner_precision:float,max_actionable_false_discovery_rate:float,
    max_actionable_false_positive_rate:float,min_actionable_runner_recall:float,
    max_actionable_missed_runners:int,
)->dict[str,Any]:
    counts=[_count(x) for x in (min_later_sample,min_later_runners,min_later_negatives,min_actionable_positive_count,max_actionable_missed_runners)]
    probs=[_prob(x) for x in (min_actionable_score_rate,min_actionable_runner_precision,max_actionable_false_discovery_rate,max_actionable_false_positive_rate,min_actionable_runner_recall)]
    criteria={
        "min_later_sample":min_later_sample,"min_later_runners":min_later_runners,
        "min_later_negatives":min_later_negatives,"min_actionable_score_rate":min_actionable_score_rate,
        "min_actionable_positive_count":min_actionable_positive_count,
        "min_actionable_runner_precision":min_actionable_runner_precision,
        "max_actionable_false_discovery_rate":max_actionable_false_discovery_rate,
        "max_actionable_false_positive_rate":max_actionable_false_positive_rate,
        "min_actionable_runner_recall":min_actionable_runner_recall,
        "max_actionable_missed_runners":max_actionable_missed_runners,
    }
    if any(x is None for x in counts+probs) or any(x<1 for x in counts[:4]):
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["valid_explicit_post_candidate_criteria"],"criteria":criteria,**AUTHORITY}
    if not isinstance(comparison,dict) or comparison.get("comparison_status")!="PROSPECTIVE_COMPARISON_COMPLETE":
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["complete_post_candidate_comparison"],"criteria":criteria,**AUTHORITY}
    actionable=comparison.get("actionable_score_threshold_metrics")
    alerts=comparison.get("actual_alert_admission_metrics")
    score_metrics=comparison.get("score_threshold_metrics")
    if (
        not isinstance(actionable,dict) or actionable.get("universe")!="actionable_score"
        or not isinstance(alerts,dict) or alerts.get("universe")!="all_labeled"
        or not isinstance(score_metrics,dict) or score_metrics.get("universe")!="numeric_score"
    ):
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["explicit_metric_universes"],"criteria":criteria,**AUTHORITY}

    sample=_count(comparison.get("sample_count"))
    runners=_count(comparison.get("runner_count"))
    negatives=_count(comparison.get("negative_count"))
    actionable_rate=_prob(comparison.get("actionable_score_rate"))
    positives=_count(actionable.get("positive_count"))
    missed=_count(actionable.get("missed_runner_count"))
    precision=_prob(actionable.get("runner_precision"))
    fdr=_prob(actionable.get("false_discovery_rate"))
    fpr=_prob(actionable.get("false_positive_rate"))
    recall=_prob(actionable.get("runner_recall"))
    checks={
        "sufficient_later_sample":sample is not None and sample>=counts[0],
        "sufficient_later_runners":runners is not None and runners>=counts[1],
        "sufficient_later_negatives":negatives is not None and negatives>=counts[2],
        "sufficient_actionable_score_coverage":actionable_rate is not None and actionable_rate>=probs[0],
        "sufficient_actionable_threshold_positives":positives is not None and positives>=counts[3],
        "minimum_actionable_runner_precision":precision is not None and precision>=probs[1],
        "maximum_actionable_false_discovery_rate":fdr is not None and fdr<=probs[2],
        "maximum_actionable_false_positive_rate":fpr is not None and fpr<=probs[3],
        "minimum_actionable_runner_recall":recall is not None and recall>=probs[4],
        "maximum_actionable_missed_runners":missed is not None and missed<=counts[4],
    }
    failed=[k for k,v in checks.items() if not v]
    comparison_evidence=deepcopy(comparison)
    try:
        comparison_evidence_sha256=content_sha256(comparison_evidence)
    except (TypeError,ValueError,OverflowError,RecursionError):
        return {
            "status":"UNKNOWN","readiness_status":"NOT_READY",
            "missing":["canonical_post_candidate_comparison_evidence"],
            "criteria":criteria,**AUTHORITY,
        }
    return {
        "status":"OBSERVED",
        "readiness_status":"READY_FOR_PAPER_POLICY_REVIEW" if not failed else "NOT_READY",
        "candidate_version":comparison.get("candidate_version"),
        "evidence_sha256":comparison.get("evidence_sha256"),
        "candidate_threshold":comparison.get("candidate_threshold"),
        "candidate_cutoff":comparison.get("candidate_cutoff"),"comparison_as_of":comparison.get("as_of"),
        "sample_count":sample,"runner_count":runners,"negative_count":negatives,
        "unknown_score_count":comparison.get("unknown_score_count"),
        "unknown_score_rate":comparison.get("unknown_score_rate"),
        "actionable_score_count":comparison.get("actionable_score_count"),
        "actionable_score_rate":comparison.get("actionable_score_rate"),
        "non_actionable_numeric_score_count":comparison.get("non_actionable_numeric_score_count"),
        "non_actionable_numeric_score_rate":comparison.get("non_actionable_numeric_score_rate"),
        "score_threshold_metrics":score_metrics,
        "actionable_score_threshold_metrics":actionable,
        "actual_alert_admission_metrics":alerts,
        "comparison_evidence":comparison_evidence,
        "comparison_evidence_sha256":comparison_evidence_sha256,
        "checks":checks,"criteria":criteria,"missing":failed,
        "requires_separate_operator_policy_provisioning":True,
        "requires_explicit_activation":True,
        **AUTHORITY,
    }
