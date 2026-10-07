#!/usr/bin/env python3
"""Frozen V3 execution diagnostics using actual post-decision market snapshots.

Evidence-only. Scenarios are predeclared sensitivity tests, not optimized rules.
"""
from __future__ import annotations
import argparse,asyncio,json,math,os
from collections import defaultdict
from datetime import datetime,timezone
from statistics import median
import asyncpg

POLICY="genesis-evidence-paper-v3"; BOUNDARY="2026-10-05T12:46:27.418241+00:00"
SCENARIOS=[
 {"name":"fixed_15m_cost_1pct","hold_sec":900,"cost_pct":0.01,"latency_sec":15},
 {"name":"fixed_30m_cost_2pct","hold_sec":1800,"cost_pct":0.02,"latency_sec":30},
 {"name":"fixed_60m_cost_3pct","hold_sec":3600,"cost_pct":0.03,"latency_sec":30},
]
ROWS="""select d.mint,d.decision,d.decided_at,mt.completed_at
from intelligence_paper_decisions d join migration_tracks mt on mt.track_id=d.track_id
where d.policy_version=$1 and d.prospective_boundary=$2 and mt.completed_at>=d.decided_at
and mt.meta->'canonical_measured_outcome' is not null order by d.id"""
SNAPS="""select captured_at,price_usd,liquidity_usd from market_snapshots
where mint=$1 and captured_at >= $2 and captured_at <= $3 order by captured_at"""

def dsn():return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def q(v,p):
 if not v:return None
 a=sorted(v); pos=(len(a)-1)*p; lo=int(pos); hi=min(lo+1,len(a)-1); f=pos-lo
 return a[lo]+(a[hi]-a[lo])*f
def summarize(vals):
 if not vals:return {"n":0}
 wins=sum(v>1 for v in vals)
 return {"n":len(vals),"win_rate":wins/len(vals),"median_multiple":median(vals),
 "p25_multiple":q(vals,.25),"p75_multiple":q(vals,.75),"mean_multiple":sum(vals)/len(vals)}
def nearest_after(snaps,target):
 return next((s for s in snaps if s["captured_at"]>=target and s["price_usd"] and float(s["price_usd"])>0),None)
async def run():
 c=await asyncpg.connect(dsn())
 try:
  rows=await c.fetch(ROWS,POLICY,datetime.fromisoformat(BOUNDARY)); out={}
  for sc in SCENARIOS:
   groups=defaultdict(list); skipped=defaultdict(int)
   for r in rows:
    snaps=await c.fetch(SNAPS,r["mint"],r["decided_at"],r["completed_at"])
    from datetime import timedelta
    ent=nearest_after(snaps,r["decided_at"]+timedelta(seconds=sc["latency_sec"]))
    ex=nearest_after(snaps,r["decided_at"]+timedelta(seconds=sc["hold_sec"]))
    if not ent or not ex: skipped[r["decision"]]+=1; continue
    ep=float(ent["price_usd"]); xp=float(ex["price_usd"])
    gross=xp/ep; net=gross*(1-sc["cost_pct"])
    groups[r["decision"]].append(net)
   out[sc["name"]]={"assumptions":sc,"by_decision":{k:summarize(v) for k,v in groups.items()},"skipped_no_path":dict(skipped)}
  return {"version":"genesis-execution-diagnostic-v1","policy_version":POLICY,"boundary":BOUNDARY,
   "method":"first observed price at/after fixed latency; first observed price at/after fixed hold; multiplicative round-trip cost haircut",
   "warning":"diagnostic sensitivity only; scenarios are not optimized and do not grant trading authority",
   "scenarios":out,"threshold_retuning_permitted":False,"live_trading_authority":False,
   "generated_at":datetime.now(timezone.utc).isoformat()}
 finally:await c.close()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output");a=ap.parse_args()
 p=json.dumps(asyncio.run(run()),indent=2,sort_keys=True)
 if a.output:open(a.output,"w",encoding="utf-8").write(p+"\n")
 print(p)
if __name__=="__main__":main()
