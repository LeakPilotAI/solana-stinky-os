#!/usr/bin/env python3
"""Robust prospective V3 diagnostic. Evidence-only; never grants trading authority."""
from __future__ import annotations
import argparse, asyncio, json, math, os
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
import asyncpg

POLICY_VERSION="genesis-evidence-paper-v3"
BOUNDARY="2026-10-05T12:46:27.418241+00:00"
QUERY="""SELECT ipd.decision,ipd.decided_at,iss.score_payload,
mt.completed_at,mt.meta->'canonical_measured_outcome' AS outcome
FROM intelligence_paper_decisions ipd
JOIN intelligence_shadow_scores iss ON iss.id=ipd.shadow_score_id
JOIN migration_tracks mt ON mt.track_id=ipd.track_id
WHERE ipd.policy_version=$1 AND ipd.prospective_boundary=$2 ORDER BY ipd.id"""

def dsn(): return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def obj(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except json.JSONDecodeError:return None
    return v if isinstance(v,dict) else None
def wilson(k,n,z=1.96):
    if not n:return None
    p=k/n; den=1+z*z/n; c=(p+z*z/(2*n))/den
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return {"rate":p,"ci95":[c-h,c+h]}
def two_prop(k1,n1,k2,n2):
    if not n1 or not n2:return None
    p1=k1/n1;p2=k2/n2;p=(k1+k2)/(n1+n2)
    se=math.sqrt(p*(1-p)*(1/n1+1/n2))
    if not se:return {"difference":p1-p2,"z":None,"p_two_sided":None}
    z=(p1-p2)/se
    return {"difference":p1-p2,"z":z,"p_two_sided":math.erfc(abs(z)/math.sqrt(2))}
def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        o=obj(r["outcome"]); s=obj(r["score_payload"])
        if r["completed_at"] is None or not o: continue
        if r["completed_at"] < r["decided_at"]: raise RuntimeError("contaminated prospective row")
        peak=o.get("peak_multiple"); ep=o.get("entry_price_usd"); fl=o.get("final_liquidity_usd")
        plausible=isinstance(ep,(int,float)) and ep>=1e-8 and isinstance(fl,(int,float)) and fl>=1000
        groups[r["decision"]].append({"label":o.get("label"),"peak":peak,"plausible":plausible,"regime":s.get("regime"),"score":s.get("score")})
    def gstats(vals,plausible_only=False):
        v=[x for x in vals if (x["plausible"] or not plausible_only)]
        peaks=sorted(float(x["peak"]) for x in v if isinstance(x["peak"],(int,float)))
        k=sum(x["label"]=="RUNNER" for x in v); n=len(v)
        return {"n":n,"runners":k,"runner":wilson(k,n),"median_peak":median(peaks) if peaks else None,
                "mean_peak_cap10":sum(min(x,10) for x in peaks)/len(peaks) if peaks else None}
    raw={k:gstats(v) for k,v in groups.items()}
    plausible={k:gstats(v,True) for k,v in groups.items()}
    def comp(stats):
        a=stats.get("PAPER_WOULD_ENTER",{}); b=stats.get("PAPER_PASS",{})
        return two_prop(a.get("runners",0),a.get("n",0),b.get("runners",0),b.get("n",0))
    return {"policy_version":POLICY_VERSION,"prospective_boundary":BOUNDARY,
            "diagnostic_plausibility_screen":{"entry_price_usd_min":1e-8,"final_liquidity_usd_min":1000,
              "note":"diagnostic sensitivity screen only; not a trading/admission rule"},
            "raw":raw,"plausibility_screened":plausible,
            "enter_vs_pass_raw":comp(raw),"enter_vs_pass_screened":comp(plausible),
            "threshold_retuning_permitted":False,"live_trading_authority":False,
            "generated_at":datetime.now(timezone.utc).isoformat()}
async def run():
    c=await asyncpg.connect(dsn())
    try:return summarize(await c.fetch(QUERY,POLICY_VERSION,datetime.fromisoformat(BOUNDARY)))
    finally:await c.close()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output"); a=ap.parse_args()
    payload=json.dumps(asyncio.run(run()),indent=2,sort_keys=True)
    if a.output: open(a.output,"w",encoding="utf-8").write(payload+"\n")
    print(payload)
if __name__=="__main__":main()
