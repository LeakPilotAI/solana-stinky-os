#!/usr/bin/env python3
"""Prospective evidence-only T+60 shadow scorer."""
from __future__ import annotations
import argparse,asyncio,hashlib,importlib.util,json,os
from datetime import datetime,timezone
from pathlib import Path
import asyncpg
ROOT=Path(__file__).resolve().parents[1]
SCORE_PATH=ROOT/"scripts"/"build_genesis_evidence_score.py"
DEFAULT_CAL=ROOT/"logs"/"research"/"genesis-calibration-profiles.json"
SHADOW_VERSION="prospective-shadow-v1"
HORIZON_SEC=60
QUERY="""SELECT mt.track_id,mt.mint,mt.migration_at,
 mt.migration_at + ($1 * interval '1 second') cutoff_at,
 s.captured_at market_observed_at,s.price_usd,s.liquidity_usd,s.volume_m5_usd,s.market_cap_usd,
 b.early_buyer_count,b.meaningful_buyer_count,b.buyer_sol_spent
FROM migration_tracks mt
LEFT JOIN LATERAL (
 SELECT ms.captured_at,ms.price_usd,ms.liquidity_usd,ms.volume_m5_usd,ms.market_cap_usd
 FROM market_snapshots ms WHERE ms.mint=mt.mint
 AND ms.captured_at <= mt.migration_at + ($1 * interval '1 second')
 ORDER BY ms.captured_at DESC,ms.snapshot_id DESC LIMIT 1) s ON TRUE
LEFT JOIN LATERAL (
 SELECT count(*)::int early_buyer_count,count(*) FILTER (WHERE mb.is_meaningful)::int meaningful_buyer_count,sum(mb.sol_spent) buyer_sol_spent
 FROM migration_buyers mb WHERE mb.track_id=mt.track_id
 AND mb.bought_at <= mt.migration_at + ($1 * interval '1 second')) b ON TRUE
WHERE mt.migration_at >= $5
AND mt.migration_at + ($1 * interval '1 second') <= $2
AND NOT EXISTS (SELECT 1 FROM intelligence_shadow_scores iss
 WHERE iss.track_id=mt.track_id AND iss.score_version=$3 AND iss.horizon_sec=$1)
ORDER BY mt.migration_at,mt.track_id LIMIT $4"""
def dsn(): return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@localhost:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)
def score_module():
    spec=importlib.util.spec_from_file_location("ges",SCORE_PATH)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def features(row):
    return {k:row.get(k) for k in ("price_usd","liquidity_usd","volume_m5_usd","market_cap_usd","early_buyer_count","meaningful_buyer_count","buyer_sol_spent")}
async def build_scores(cal_path:Path,limit:int,boundary:datetime):
    raw=cal_path.read_bytes(); cal=json.loads(raw); scorer=score_module(); clock=datetime.now(timezone.utc)
    conn=await asyncpg.connect(dsn())
    try:
        rows=await conn.fetch(QUERY,HORIZON_SEC,clock,scorer.SCORE_VERSION,limit,boundary); out=[]
        for rec in rows:
            row=dict(rec); cutoff=row["cutoff_at"]; observed=row.get("market_observed_at")
            if cutoff>clock or (observed is not None and observed>cutoff): raise RuntimeError("prospective as-of leakage invariant violated")
            payload=features(row); score=scorer.score_row(payload,cal)
            if score["trade_signal"] or score["predictive_authority"] or score["authority"]!="evidence_only": raise RuntimeError("shadow authority invariant violated")
            out.append((row,payload,score,scorer.SCORE_VERSION,cal.get("profile_version","UNKNOWN"),hashlib.sha256(raw).hexdigest(),clock))
        return out
    finally: await conn.close()
async def persist(items):
    conn=await asyncpg.connect(dsn()); inserted=0
    try:
        for row,payload,score,score_version,cal_version,cal_hash,clock in items:
            args=(row["track_id"],row["mint"],SHADOW_VERSION,score_version,cal_version,cal_hash,HORIZON_SEC,row["migration_at"],row["cutoff_at"],clock,row.get("market_observed_at"),json.dumps(payload,default=str),json.dumps(score,default=str))
            result=await conn.execute("INSERT INTO intelligence_shadow_scores (track_id,mint,shadow_version,score_version,calibration_version,calibration_sha256,horizon_sec,migration_at,cutoff_at,scored_at,market_observed_at,feature_payload,score_payload,authority,trade_signal,predictive_authority) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb,'evidence_only',false,false) ON CONFLICT(track_id,score_version,horizon_sec) DO NOTHING",*args)
            inserted+=int(result.endswith("1"))
        return inserted
    finally: await conn.close()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--calibration",type=Path,default=DEFAULT_CAL); ap.add_argument("--limit",type=int,default=500); ap.add_argument("--boundary",required=True); a=ap.parse_args()
    items=asyncio.run(build_scores(a.calibration,a.limit,datetime.fromisoformat(a.boundary))); inserted=asyncio.run(persist(items))
    print(json.dumps({"eligible":len(items),"inserted":inserted,"shadow_version":SHADOW_VERSION},sort_keys=True))
if __name__=="__main__": main()
