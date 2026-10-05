#!/usr/bin/env python3
"""Translate immutable Genesis evidence scores into PAPER-only decisions."""
from __future__ import annotations
import argparse,asyncio,json,os
from datetime import datetime,timezone
import asyncpg
POLICY_VERSION="genesis-evidence-paper-v3"
MIN_WOULD_ENTER_SCORE=50.0
AUTHORITY={"paper_only":True,"live_execution":False,"trading_authority":False,"trade_signal":False,"recommendation_authority":False}
DDL="""CREATE TABLE IF NOT EXISTS intelligence_paper_decisions (
 id bigserial PRIMARY KEY, shadow_score_id bigint NOT NULL REFERENCES intelligence_shadow_scores(id),
 track_id uuid NOT NULL, mint text NOT NULL, policy_version text NOT NULL, score_version text NOT NULL,
 prospective_boundary timestamptz NOT NULL, decided_at timestamptz NOT NULL, decision text NOT NULL,
 rationale jsonb NOT NULL, authority jsonb NOT NULL,
 UNIQUE(shadow_score_id,policy_version))"""
QUERY="""SELECT iss.id,iss.track_id,iss.mint,iss.score_version,iss.migration_at,iss.scored_at,iss.score_payload
FROM intelligence_shadow_scores iss
JOIN migration_tracks mt ON mt.track_id=iss.track_id
WHERE iss.migration_at >= $1 AND iss.scored_at >= $1
AND mt.completed_at IS NULL
AND NOT EXISTS (SELECT 1 FROM intelligence_paper_decisions ipd
 WHERE ipd.shadow_score_id=iss.id AND ipd.policy_version=$2)
ORDER BY iss.scored_at,iss.id LIMIT $3"""
def dsn(): return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@127.0.0.1:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def decide(payload):
    if isinstance(payload,str):
        payload=json.loads(payload)
    status=payload.get("status") if isinstance(payload,dict) else None
    score=payload.get("score") if isinstance(payload,dict) else None
    if status!="KNOWN" or score is None:
        return "NO_DECISION",{"reason":"score_insufficient_or_unknown","score_status":status,"score":score,"threshold":MIN_WOULD_ENTER_SCORE}
    value=float(score)
    action="PAPER_WOULD_ENTER" if value>MIN_WOULD_ENTER_SCORE else "PAPER_PASS"
    return action,{"reason":"predeclared_evidence_score_neutral_point","score_status":status,"score":value,"threshold":MIN_WOULD_ENTER_SCORE,"comparison":">" if action=="PAPER_WOULD_ENTER" else "<="}
async def run(boundary,limit):
    conn=await asyncpg.connect(dsn()); now=datetime.now(timezone.utc); inserted=0; counts={}
    try:
        rows=await conn.fetch(QUERY,boundary,POLICY_VERSION,limit)
        for r in rows:
            action,rationale=decide(r["score_payload"])
            authority={**AUTHORITY,"source_score_authority":"evidence_only","predictive_authority":False}
            result=await conn.execute("""INSERT INTO intelligence_paper_decisions
            (shadow_score_id,track_id,mint,policy_version,score_version,prospective_boundary,decided_at,decision,rationale,authority)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)
            ON CONFLICT(shadow_score_id,policy_version) DO NOTHING""",
            r["id"],r["track_id"],r["mint"],POLICY_VERSION,r["score_version"],boundary,now,action,json.dumps(rationale),json.dumps(authority))
            inserted+=int(result.endswith("1")); counts[action]=counts.get(action,0)+1
        return {"eligible":len(rows),"inserted":inserted,"decisions":counts,"policy_version":POLICY_VERSION}
    finally: await conn.close()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--boundary",required=True); ap.add_argument("--limit",type=int,default=500); a=ap.parse_args()
    print(json.dumps(asyncio.run(run(datetime.fromisoformat(a.boundary),a.limit)),sort_keys=True))
if __name__=="__main__": main()
