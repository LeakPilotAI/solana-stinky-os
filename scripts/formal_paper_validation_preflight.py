"""Fail-closed local preflight for formal Genesis paper validation.

This inventories real immutable paper evidence. It does not invent release
criteria, provision/activate policy, or grant execution authority.
"""
from __future__ import annotations
import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"api"/"src"))
from stinky_api.db import SessionLocal

AUTHORITY={"paper_only":True,"read_only":True,"performance_validation":False,
"thresholds_invented":False,"automatic_activation":False,"live_execution":False,
"trading_authority":False,"rpc_contacted":False,"transaction_signed":False,
"order_submitted":False,"wallet_mutated":False}

async def inspect():
    async with SessionLocal() as s:
        active=(await s.execute(text("""SELECT a.policy_version,r.policy_sha256,r.policy_payload,
          r.created_at,a.activated_at FROM paper_policy_active a
          JOIN paper_policy_registry r ON r.policy_version=a.policy_version
          WHERE a.singleton=TRUE"""))).mappings().first()
        counts=(await s.execute(text("""SELECT
          (SELECT count(*) FROM paper_prospective_candidate) candidates,
          (SELECT count(*) FROM paper_runtime_intake) intakes,
          (SELECT count(*) FROM paper_runtime_record) runtime_records,
          (SELECT count(*) FROM paper_runtime_record WHERE paper_status='SIMULATED_CLOSED') closed_simulations"""))).mappings().one()
        identities=(await s.execute(text("""SELECT policy_sha256,policy_version,policy_evidence_backed,
          count(*) record_count,
          count(*) FILTER (WHERE paper_status='SIMULATED_CLOSED') closed_count
          FROM paper_runtime_record WHERE policy_sha256 IS NOT NULL
          GROUP BY policy_sha256,policy_version,policy_evidence_backed
          ORDER BY min(created_at),policy_sha256"""))).mappings().all()
    blockers=[]
    if active is None: blockers.append("no_active_immutable_paper_policy")
    if not identities: blockers.append("no_first_class_policy_cohort_records")
    if int(counts["closed_simulations"])==0: blockers.append("no_closed_paper_simulations")
    return {"status":"READY_FOR_CRITERIA_BOUND_VALIDATION" if not blockers else "NOT_READY",
      "as_of":datetime.now(timezone.utc).isoformat(),"active_policy":dict(active) if active else None,
      "counts":dict(counts),"policy_cohorts":[dict(x) for x in identities],"blockers":blockers,
      "next_gate":"explicit_release_criteria_plus_single_immutable_policy_cohort",
      **AUTHORITY}

async def main():
    result=await inspect()
    print(json.dumps(result,sort_keys=True,default=str,indent=2))
    print("[validation] FORMAL PAPER VALIDATION PREFLIGHT "+result["status"])
    return 0 if result["status"]=="READY_FOR_CRITERIA_BOUND_VALIDATION" else 2

if __name__=="__main__": raise SystemExit(asyncio.run(main()))
