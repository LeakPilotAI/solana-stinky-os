#!/usr/bin/env python3
"""Create immutable prospective PAPER execution plans from V3 ENTER decisions.

Policy is deliberately frozen before future outcomes. It does not execute trades.
"""
from __future__ import annotations
import argparse,asyncio,json,os
from datetime import datetime,timezone
import asyncpg

POLICY_VERSION="genesis-paper-execution-v1"
SOURCE_POLICY="genesis-evidence-paper-v3"
ENTRY_LATENCY_SEC=30
MAX_HOLD_SEC=900
ROUND_TRIP_COST_PCT=0.02
MIN_ENTRY_LIQUIDITY_USD=1000.0
AUTHORITY={"paper_only":True,"live_execution":False,"trading_authority":False,"trade_signal":False}
DDL="""CREATE TABLE IF NOT EXISTS intelligence_paper_execution_plans (
 id bigserial PRIMARY KEY,
 paper_decision_id bigint NOT NULL REFERENCES intelligence_paper_decisions(id),
 track_id uuid NOT NULL,mint text NOT NULL,execution_policy_version text NOT NULL,
 source_policy_version text NOT NULL,prospective_boundary timestamptz NOT NULL,
 planned_at timestamptz NOT NULL,plan jsonb NOT NULL,authority jsonb NOT NULL,
 UNIQUE(paper_decision_id,execution_policy_version))"""
QUERY="""SELECT d.id,d.track_id,d.mint,d.prospective_boundary,d.decided_at
FROM intelligence_paper_decisions d JOIN migration_tracks mt ON mt.track_id=d.track_id
WHERE d.policy_version=$1 AND d.decision='PAPER_WOULD_ENTER'
AND d.decided_at >= $2 AND mt.completed_at IS NULL
AND NOT EXISTS (SELECT 1 FROM intelligence_paper_execution_plans p
 WHERE p.paper_decision_id=d.id AND p.execution_policy_version=$3)
ORDER BY d.decided_at,d.id LIMIT $4"""
def dsn():return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def frozen_plan():
 return {"entry":{"latency_sec":ENTRY_LATENCY_SEC,"min_liquidity_usd":MIN_ENTRY_LIQUIDITY_USD},
 "exit":{"type":"fixed_time","max_hold_sec":MAX_HOLD_SEC},
 "cost_model":{"round_trip_cost_pct":ROUND_TRIP_COST_PCT},
 "note":"predeclared prospective paper policy; no outcome-dependent tuning"}
async def run(boundary,limit):
 c=await asyncpg.connect(dsn()); inserted=0
 try:
  await c.execute(DDL); rows=await c.fetch(QUERY,SOURCE_POLICY,boundary,POLICY_VERSION,limit)
  for r in rows:
   result=await c.execute("""INSERT INTO intelligence_paper_execution_plans
   (paper_decision_id,track_id,mint,execution_policy_version,source_policy_version,
   prospective_boundary,planned_at,plan,authority)
   VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb)
   ON CONFLICT(paper_decision_id,execution_policy_version) DO NOTHING""",
   r["id"],r["track_id"],r["mint"],POLICY_VERSION,SOURCE_POLICY,boundary,
   datetime.now(timezone.utc),json.dumps(frozen_plan()),json.dumps(AUTHORITY))
   inserted+=int(result.endswith("1"))
  return {"eligible":len(rows),"inserted":inserted,"execution_policy_version":POLICY_VERSION,
          "live_execution":False}
 finally:await c.close()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--boundary",required=True);ap.add_argument("--limit",type=int,default=500);a=ap.parse_args()
 print(json.dumps(asyncio.run(run(datetime.fromisoformat(a.boundary),a.limit)),sort_keys=True))
if __name__=="__main__":main()
