#!/usr/bin/env python3
"""Read-only report for frozen prospective paper execution plans."""
from __future__ import annotations
import argparse,asyncio,json,os
from datetime import datetime,timezone,timedelta
import asyncpg
POLICY="genesis-paper-execution-v1"
ENTRY_LATENCY=30
HOLD=900
COST=.02
MIN_LIQ=1000.0
QUERY="""select p.id,p.mint,d.decided_at,p.plan from intelligence_paper_execution_plans p
join intelligence_paper_decisions d on d.id=p.paper_decision_id
where p.execution_policy_version=$1 order by p.id"""
def dsn():return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def mature(t,now):return now>=t+timedelta(seconds=ENTRY_LATENCY+HOLD)
async def run():
 c=await asyncpg.connect(dsn()); now=datetime.now(timezone.utc); results=[]
 try:
  for r in await c.fetch(QUERY,POLICY):
   if not mature(r["decided_at"],now):
    results.append({"plan_id":r["id"],"status":"PENDING"});continue
   et=r["decided_at"]+timedelta(seconds=ENTRY_LATENCY);xt=et+timedelta(seconds=HOLD)
   snaps=await c.fetch("""select captured_at,price_usd,liquidity_usd from market_snapshots
    where mint=$1 and captured_at >= $2 and price_usd>0 order by captured_at""",r["mint"],et)
   entry=next((x for x in snaps if x["captured_at"]<=xt),None)
   if not entry or entry["liquidity_usd"] is None or float(entry["liquidity_usd"])<MIN_LIQ:
    results.append({"plan_id":r["id"],"status":"NO_FILL"});continue
   exitrow=next((x for x in snaps if x["captured_at"]>=xt),None)
   if not exitrow:
    results.append({"plan_id":r["id"],"status":"PENDING_EXIT"});continue
   gross=float(exitrow["price_usd"])/float(entry["price_usd"])
   results.append({"plan_id":r["id"],"status":"FILLED","gross_multiple":gross,
    "net_multiple":gross*(1-COST),"entry_at":entry["captured_at"].isoformat(),
    "exit_at":exitrow["captured_at"].isoformat(),"entry_liquidity_usd":float(entry["liquidity_usd"])})
  counts={}
  for x in results:counts[x["status"]]=counts.get(x["status"],0)+1
  return {"policy":POLICY,"counts":counts,"results":results,"read_only":True,
   "policy_retuning_permitted":False,"live_trading_authority":False,"generated_at":now.isoformat()}
 finally:await c.close()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output");a=ap.parse_args()
 s=json.dumps(asyncio.run(run()),indent=2,sort_keys=True)
 if a.output:open(a.output,"w",encoding="utf-8").write(s+"\n")
 print(s)
if __name__=="__main__":main()
