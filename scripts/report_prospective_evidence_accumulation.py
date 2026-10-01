"""Criteria-free prospective evidence accumulation report.

Measures the real pre-policy evidence corpus. It deliberately makes no
sufficiency judgment and cannot provision or activate a policy.
"""
from __future__ import annotations
import asyncio,json,sys
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import text
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"api"/"src"))
from stinky_api.db import SessionLocal
from stinky_api.prospective_paper_intake_producer import PRODUCER_VERSION,FILTER_VERSION,cohort_signature
from stinky_api.market_path_patterns import canonical_pattern_hash

AUTHORITY={"paper_only":True,"read_only":True,"criteria_applied":False,
"sufficiency_judgment":False,"threshold_proposal":None,"automatic_activation":False,
"performance_validation":False,"live_execution":False,"trading_authority":False,
"rpc_contacted":False,"transaction_signed":False,"order_submitted":False,"wallet_mutated":False}

async def report():
    pattern_hash=canonical_pattern_hash(cohort_signature(str(FILTER_VERSION or "UNKNOWN")))
    async with SessionLocal() as s:
        state=(await s.execute(text("SELECT prospective_started_at FROM paper_intake_producer_state WHERE singleton=TRUE"))).first()
        started=state[0] if state else None
        row=(await s.execute(text("""SELECT
          count(*) AS candidates,
          count(*) FILTER (WHERE canonical_outcome IN ('RUNNER','HELD','FADE')) AS closed,
          count(*) FILTER (WHERE canonical_outcome='RUNNER') AS runners,
          count(*) FILTER (WHERE canonical_outcome='HELD') AS held,
          count(*) FILTER (WHERE canonical_outcome='FADE') AS fades,
          count(*) FILTER (WHERE canonical_outcome IS NULL OR canonical_outcome NOT IN ('RUNNER','HELD','FADE')) AS unresolved,
          min(decided_at) AS first_decided_at,max(decided_at) AS latest_decided_at,
          max(outcome_observed_at) AS latest_outcome_observed_at
          FROM paper_prospective_candidate
          WHERE producer_version=:version AND cohort_pattern_hash=:pattern_hash
            AND (:started IS NULL OR decided_at>=:started)"""),
          {"version":PRODUCER_VERSION,"pattern_hash":pattern_hash,"started":started})).mappings().one()
        market=(await s.execute(text("""SELECT horizon,count(*) AS samples
          FROM market_outcome_observations
          WHERE pattern_hash=:pattern_hash AND observed_at IS NOT NULL
          GROUP BY horizon ORDER BY horizon"""),{"pattern_hash":pattern_hash})).all()
    counts={k:(int(row[k]) if row[k] is not None else 0) for k in ("candidates","closed","runners","held","fades","unresolved")}
    return {"status":"OBSERVED","as_of":datetime.now(timezone.utc).isoformat(),
      "producer_version":PRODUCER_VERSION,"filter_version":str(FILTER_VERSION or "UNKNOWN"),
      "cohort_pattern_hash":pattern_hash,"prospective_started_at":started,
      "counts":counts,"represented_outcome_classes":sum(counts[k]>0 for k in ("runners","held","fades")),
      "market_cap_samples_by_horizon":{str(h):int(n) for h,n in market},
      "first_decided_at":row["first_decided_at"],"latest_decided_at":row["latest_decided_at"],
      "latest_outcome_observed_at":row["latest_outcome_observed_at"],
      "interpretation":"MEASUREMENT_ONLY_NO_SUFFICIENCY_CRITERIA",**AUTHORITY}

async def main():
    print(json.dumps(await report(),sort_keys=True,default=str,indent=2))
    print("[evidence] PROSPECTIVE ACCUMULATION OBSERVED — no sufficiency criteria applied")
    return 0
if __name__=="__main__": raise SystemExit(asyncio.run(main()))
