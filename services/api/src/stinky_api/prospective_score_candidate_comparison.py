"""Prospective comparison of a frozen score candidate against later outcomes.

The comparison starts strictly after the candidate evidence cutoff. It does not
provision or activate the candidate and keeps score-threshold discrimination
separate from the full pipeline's historical alert_ok admission.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math
import hashlib
import json
from typing import Any
from sqlalchemy import text

AUTHORITY={
    "interpretation":"POST_CANDIDATE_PROSPECTIVE_COMPARISON",
    "read_only":True,"evidence_only":True,"paper_only":True,
    "candidate_activation":False,"policy_provisioning_authority":False,
    "live_threshold_changed":False,"trading_authority":False,"live_execution":False,
}

def _dt(v:Any)->datetime|None:
    if isinstance(v,datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        x=datetime.fromisoformat(str(v).strip().replace("Z","+00:00"))
    except (TypeError,ValueError):
        return None
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)

def _positive_count(v:Any)->int|None:
    if v is None or isinstance(v,bool): return None
    if isinstance(v,float) and not v.is_integer(): return None
    try: n=int(v)
    except (TypeError,ValueError): return None
    return n if n>=1 else None

def _metrics(rows:list[dict[str,Any]],positive_key:str,*,universe:str)->dict[str,Any]:
    if universe=="numeric_score":
        eligible=[r for r in rows if r.get("stinky_score") is not None]
    elif universe=="actionable_score":
        eligible=[r for r in rows if r.get("stinky_score") is not None and r.get("score_actionable") is True]
    elif universe=="all_labeled":
        eligible=list(rows)
    else:
        raise ValueError("unknown metric universe")
    runners=[r for r in eligible if r["label"]=="RUNNER"]
    negatives=[r for r in eligible if r["label"]!="RUNNER"]
    positive=[r for r in eligible if bool(r[positive_key])]
    tp=[r for r in positive if r["label"]=="RUNNER"]
    fp=[r for r in positive if r["label"]!="RUNNER"]
    return {
        "universe":universe,
        "eligible_count":len(eligible),
        "runner_count":len(runners),
        "negative_count":len(negatives),
        "positive_count":len(positive),
        "runner_precision":len(tp)/len(positive) if positive else None,
        "false_discovery_rate":len(fp)/len(positive) if positive else None,
        "false_positive_rate":len(fp)/len(negatives) if negatives else None,
        "runner_recall":len(tp)/len(runners) if runners else None,
        "missed_runner_count":len(runners)-len(tp),
    }

async def compare_score_paper_candidate(
    session, *, candidate:dict[str,Any], as_of:datetime|str,
    min_sample:int,min_runners:int,min_negatives:int,
)->dict[str,Any]:
    required_counts=[_positive_count(x) for x in (min_sample,min_runners,min_negatives)]
    if any(x is None for x in required_counts):
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["valid_explicit_comparison_criteria"],**AUTHORITY}
    if not isinstance(candidate,dict) or candidate.get("status")!="PAPER_CANDIDATE_ARTIFACT":
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["paper_candidate_artifact"],**AUTHORITY}
    payload=candidate.get("payload")
    if not isinstance(payload,dict):
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["candidate_payload"],**AUTHORITY}
    try:
        canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError):
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["canonical_candidate_payload"],**AUTHORITY}
    expected_sha=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expected_version=f"{payload.get('schema_version')}:{expected_sha[:16]}"
    if candidate.get("evidence_sha256")!=expected_sha or candidate.get("candidate_version")!=expected_version:
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["candidate_identity_mismatch"],**AUTHORITY}
    versions=payload.get("versions")
    cutoff=_dt(payload.get("evaluation_as_of")) if isinstance(payload,dict) else None
    end=_dt(as_of)
    try:
        threshold=float(payload.get("selected_threshold")) if isinstance(payload,dict) else math.nan
    except (TypeError,ValueError):
        threshold=math.nan
    if (
        not isinstance(versions,dict) or cutoff is None or end is None or end<=cutoff
        or not math.isfinite(threshold) or not 0.0<=threshold<=100.0
        or not candidate.get("candidate_version") or not candidate.get("evidence_sha256")
    ):
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["valid_candidate_identity_window_or_threshold"],**AUTHORITY}
    intel=str(versions.get("intelligence_model_version") or "").strip()
    score=str(versions.get("score_model_version") or "").strip()
    label_version=str(versions.get("outcome_label_version") or "").strip()
    if not intel or not score or not label_version:
        return {"status":"UNKNOWN","comparison_status":"NOT_COMPARISON_READY","missing":["candidate_model_versions"],**AUTHORITY}

    rows=(await session.execute(text("""
        SELECT DISTINCT ON (mi.mint)
          mi.mint, mi.inspected_at, mi.stinky_score, mi.alert_ok,
          mi.evidence->'score'->>'actionable' AS score_actionable,
          mi.evidence->'score'->>'interpretation' AS score_interpretation,
          ol.label, ol.observed_at AS outcome_observed_at, ol.ingested_at AS outcome_ingested_at
        FROM market_inspections mi
        JOIN entity_launch_outcome_labels ol
          ON ol.mint=mi.mint
         AND ol.label_version=:label_version
         AND ol.observed_at>=mi.inspected_at
         AND ol.ingested_at<=:as_of
        WHERE mi.model_version=:intelligence_model_version
          AND mi.evidence->'score'->>'model_version'=:score_model_version
          AND mi.inspected_at>:candidate_cutoff
          AND mi.inspected_at<=:as_of
        ORDER BY mi.mint, mi.inspected_at ASC, ol.observed_at ASC, ol.ingested_at ASC
    """),{
        "label_version":label_version,"as_of":end,
        "intelligence_model_version":intel,"score_model_version":score,
        "candidate_cutoff":cutoff,
    })).mappings().all()
    records=[]
    for raw in rows:
        r=dict(raw)
        if str(r.get("label") or "") not in {"RUNNER","HELD","FADE"}:
            continue
        value=r.get("stinky_score")
        score_value=None
        if value is not None and not isinstance(value,bool):
            try:
                n=float(value)
                score_value=n if math.isfinite(n) and 0.0<=n<=100.0 else None
            except (TypeError,ValueError):
                pass
        r["stinky_score"]=score_value
        r["score_actionable"]=str(r.get("score_actionable") or "").strip().lower()=="true"
        r["candidate_positive"]=score_value is not None and score_value>=threshold
        r["actionable_candidate_positive"]=r["score_actionable"] and r["candidate_positive"]
        r["actual_alert_positive"]=r.get("alert_ok") is True
        records.append(r)

    runner_count=sum(1 for r in records if r["label"]=="RUNNER")
    negative_count=sum(1 for r in records if r["label"]!="RUNNER")
    unknown_count=sum(1 for r in records if r["stinky_score"] is None)
    non_actionable_count=sum(1 for r in records if r["stinky_score"] is not None and not r["score_actionable"])
    actionable_count=sum(1 for r in records if r["stinky_score"] is not None and r["score_actionable"])
    missing=[]
    if len(records)<required_counts[0]: missing.append("sufficient_later_sample")
    if runner_count<required_counts[1]: missing.append("sufficient_later_runners")
    if negative_count<required_counts[2]: missing.append("sufficient_later_negatives")
    if missing:
        return {
            "status":"OBSERVED","comparison_status":"NOT_COMPARISON_READY",
            "candidate_version":candidate["candidate_version"],"evidence_sha256":candidate["evidence_sha256"],
            "sample_count":len(records),"runner_count":runner_count,"negative_count":negative_count,
            "unknown_score_count":unknown_count,"actionable_score_count":actionable_count,
            "non_actionable_numeric_score_count":non_actionable_count,"missing":missing,**AUTHORITY,
        }

    return {
        "status":"OBSERVED","comparison_status":"PROSPECTIVE_COMPARISON_COMPLETE",
        "candidate_version":candidate["candidate_version"],"evidence_sha256":candidate["evidence_sha256"],
        "candidate_threshold":threshold,"candidate_cutoff":cutoff.isoformat(),"as_of":end.isoformat(),
        "sample_count":len(records),"runner_count":runner_count,"negative_count":negative_count,
        "unknown_score_count":unknown_count,
        "unknown_score_rate":unknown_count/len(records) if records else None,
        "actionable_score_count":actionable_count,
        "actionable_score_rate":actionable_count/len(records) if records else None,
        "non_actionable_numeric_score_count":non_actionable_count,
        "non_actionable_numeric_score_rate":non_actionable_count/len(records) if records else None,
        "score_threshold_metrics":_metrics(records,"candidate_positive",universe="numeric_score"),
        "actionable_score_threshold_metrics":_metrics(records,"actionable_candidate_positive",universe="actionable_score"),
        "actual_alert_admission_metrics":_metrics(records,"actual_alert_positive",universe="all_labeled"),
        "note":"Numeric-score discrimination, actionable-score discrimination, and actual full-pipeline alert admission are separate descriptive measurements.",
        "missing":[],**AUTHORITY,
    }
