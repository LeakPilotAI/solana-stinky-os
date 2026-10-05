#!/usr/bin/env python3
"""Export leakage-safe post-migration research rows frozen at a fixed horizon."""
from __future__ import annotations
import argparse, asyncio, csv, json, os
from pathlib import Path
import asyncpg

DATASET_VERSION = "post-migration-asof-v1"
DEFAULT_HORIZON_SEC = 60
FEATURE_COLUMNS = ["creator","destination","price_usd","liquidity_usd","volume_m5_usd","market_cap_usd","pair_address","dex_id","early_buyer_count","meaningful_buyer_count","buyer_sol_spent","entity_id"]
QUERY = r"""
WITH labeled AS (
 SELECT mt.track_id,mt.mint,mt.creator,mt.destination,mt.migration_at,
        mt.meta->'canonical_measured_outcome' outcome,
        mt.migration_at + ($1 * interval '1 second') cutoff_at
 FROM migration_tracks mt
 WHERE mt.status='completed' AND mt.meta ? 'canonical_measured_outcome'
)
SELECT l.*,
 s.captured_at market_observed_at,s.price_usd,s.liquidity_usd,s.volume_m5_usd,s.market_cap_usd,s.pair_address,s.dex_id,
 b.early_buyer_count,b.meaningful_buyer_count,b.buyer_sol_spent,
 e.entity_id,e.entity_observed_at
FROM labeled l
LEFT JOIN LATERAL (
 SELECT ms.* FROM market_snapshots ms
 WHERE ms.mint=l.mint AND ms.captured_at <= l.cutoff_at
 ORDER BY ms.captured_at DESC LIMIT 1
) s ON TRUE
LEFT JOIN LATERAL (
 SELECT count(*)::int early_buyer_count,
        count(*) FILTER (WHERE mb.is_meaningful)::int meaningful_buyer_count,
        sum(mb.sol_spent) buyer_sol_spent
 FROM migration_buyers mb
 WHERE mb.track_id=l.track_id AND mb.bought_at <= l.cutoff_at
) b ON TRUE
LEFT JOIN LATERAL (
 SELECT el.entity_id,el.observed_at entity_observed_at FROM entity_launches el
 WHERE el.mint=l.mint AND el.observed_at <= l.cutoff_at
 ORDER BY el.observed_at DESC LIMIT 1
) e ON TRUE
ORDER BY l.migration_at,l.mint
"""

def _dsn() -> str:
    return os.getenv("STINKY_DATABASE_URL","postgresql://stinky:stinky@localhost:5433/stinky").replace("postgresql+asyncpg://","postgresql://",1)

async def build_rows(horizon_sec: int) -> list[dict]:
    conn=await asyncpg.connect(_dsn())
    try:
        rows=[dict(r) for r in await conn.fetch(QUERY,horizon_sec)]
    finally:
        await conn.close()
    for row in rows:
        cutoff=row["cutoff_at"]
        for key in ("market_observed_at","entity_observed_at"):
            ts=row.get(key)
            if ts is not None and ts > cutoff:
                raise RuntimeError(f"leakage invariant violated: {key}={ts} > cutoff={cutoff}")
        raw_outcome=row.pop("outcome")
        outcome=json.loads(raw_outcome) if isinstance(raw_outcome,str) else dict(raw_outcome or {})
        row["dataset_version"]=DATASET_VERSION
        row["horizon_sec"]=horizon_sec
        row["feature_columns"]=list(FEATURE_COLUMNS)
        row["outcome_label"]=outcome.get("label")
        row["outcome_peak_multiple"]=outcome.get("peak_multiple")
        row["outcome_label_version"]=outcome.get("label_version")
        row["outcome_evidence_only"]=outcome.get("evidence_only")
        row["outcome_trade_signal"]=outcome.get("trade_signal")
        row["outcome_predictive_authority"]=outcome.get("predictive_authority")
    return rows

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--horizon-sec",type=int,default=DEFAULT_HORIZON_SEC)
    ap.add_argument("--output",type=Path,default=Path("logs/research/genesis-asof-t60.csv"))
    args=ap.parse_args()
    if args.horizon_sec < 0: raise SystemExit("--horizon-sec must be >= 0")
    rows=asyncio.run(build_rows(args.horizon_sec))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0].keys()) if rows else []
    with args.output.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    labels={}
    for row in rows: labels[row.get("outcome_label") or "UNKNOWN"]=labels.get(row.get("outcome_label") or "UNKNOWN",0)+1
    print(json.dumps({"dataset_version":DATASET_VERSION,"horizon_sec":args.horizon_sec,"rows":len(rows),"labels":labels,"output":str(args.output)},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
