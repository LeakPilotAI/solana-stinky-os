#!/usr/bin/env python3
"""Evaluate immutable prospective Genesis PAPER decisions after outcomes mature."""
from __future__ import annotations
import argparse,asyncio,json,os
from collections import Counter,defaultdict
from datetime import datetime,timezone
import asyncpg
EVAL_VERSION="genesis-expectancy-v1"
POLICY_VERSION="genesis-evidence-paper-v2"
FROZEN_THRESHOLD=50.0
MIN_MATURED_TOTAL=30
MIN_MATURED_PER_DECISION=10
QUERY="""SELECT ipd.id,ipd.decision,ipd.decided_at,ipd.policy_version,iss.score_payload,
mt.completed_at,mt.meta->'canonical_measured_outcome' AS outcome
FROM intelligence_paper_decisions ipd
JOIN intelligence_shadow_scores iss ON iss.id=ipd.shadow_score_id
JOIN migration_tracks mt ON mt.track_id=ipd.track_id
WHERE ipd.policy_version=$1 AND ipd.prospective_boundary=$2
ORDER BY ipd.id"""
def dsn(): return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def obj(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except json.JSONDecodeError:return None
    return v if isinstance(v,dict) else None
def summarize(rows,boundary):
    matured=[]; pending=0
    for r in rows:
        outcome=obj(r["outcome"])
        if r["completed_at"] is None or not outcome:
            pending+=1; continue
        if r["completed_at"] < r["decided_at"]:
            raise RuntimeError("outcome completed before immutable paper decision")
        matured.append((r,outcome))
    counts=Counter(r["decision"] for r,_ in matured)
    adequate=len(matured)>=MIN_MATURED_TOTAL and all(counts.get(d,0)>=MIN_MATURED_PER_DECISION for d in ("PAPER_WOULD_ENTER","PAPER_PASS"))
    by=defaultdict(Counter); peaks=defaultdict(list)
    for r,o in matured:
        label=o.get("label") or o.get("outcome_label") or o.get("classification") or "UNKNOWN"
        by[r["decision"]][label]+=1
        peak=o.get("peak_multiple")
        if isinstance(peak,(int,float)): peaks[r["decision"]].append(float(peak))
    return {"evaluation_version":EVAL_VERSION,"policy_version":POLICY_VERSION,"frozen_threshold":FROZEN_THRESHOLD,
      "prospective_boundary":boundary.isoformat(),"status":"EVALUATE" if adequate else "COLLECTION_MODE",
      "minimums":{"matured_total":MIN_MATURED_TOTAL,"per_decision":MIN_MATURED_PER_DECISION},
      "rows_total":len(rows),"matured":len(matured),"pending":pending,
      "matured_by_decision":dict(counts),"outcomes_by_decision":{k:dict(v) for k,v in by.items()},
      "peak_multiple_by_decision":{k:{"n":len(v),"mean":sum(v)/len(v)} for k,v in peaks.items() if v},
      "threshold_retuning_permitted":False,"live_trading_authority":False,"generated_at":datetime.now(timezone.utc).isoformat()}
async def run(boundary):
    c=await asyncpg.connect(dsn())
    try:return summarize(await c.fetch(QUERY,POLICY_VERSION,boundary),boundary)
    finally:await c.close()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--boundary",required=True); ap.add_argument("--output"); a=ap.parse_args()
    report=asyncio.run(run(datetime.fromisoformat(a.boundary))); payload=json.dumps(report,indent=2,sort_keys=True)
    if a.output: open(a.output,"w",encoding="utf-8").write(payload+"\n")
    print(payload)
if __name__=="__main__":main()
