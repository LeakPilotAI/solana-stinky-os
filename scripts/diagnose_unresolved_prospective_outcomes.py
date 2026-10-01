"""Read-only diagnosis for unresolved prospective canonical outcomes."""
from __future__ import annotations
import asyncio,json,sys
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import text
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"api"/"src"))
sys.path.insert(0,str(ROOT/"services"/"entity-resolver"/"src"))
from stinky_api.db import SessionLocal
from entity_resolver.measured_outcome_classification import classify_completed_market_path

AUTH={"paper_only":True,"read_only":True,"classification_reused":True,
"candidate_mutated":False,"automatic_activation":False,"live_execution":False,
"trading_authority":False,"rpc_contacted":False,"transaction_signed":False,
"order_submitted":False,"wallet_mutated":False}

async def diagnose():
 async with SessionLocal() as s:
  candidates=(await s.execute(text("""SELECT candidate_id,mint,decided_at
    FROM paper_prospective_candidate WHERE canonical_outcome IS NULL
    ORDER BY decided_at,candidate_id"""))).mappings().all()
  details=[]
  for c in candidates:
   track=(await s.execute(text("""SELECT track_id,migration_at,completed_at,status,
      buyers_captured,trades_observed,snapshots_taken
      FROM migration_tracks WHERE mint=:mint
      ORDER BY migration_at DESC,track_id DESC LIMIT 1"""),{"mint":c["mint"]})).mappings().first()
   launch=(await s.execute(text("""SELECT outcome_status,outcome_meta
      FROM entity_launches WHERE mint=:mint ORDER BY observed_at ASC,id ASC LIMIT 1"""),
      {"mint":c["mint"]})).mappings().first()
   ledger=(await s.execute(text("""SELECT label,label_version,observed_at,ingested_at
      FROM entity_launch_outcome_labels WHERE mint=:mint
      ORDER BY observed_at ASC,ingested_at ASC,id ASC LIMIT 1"""),
      {"mint":c["mint"]})).mappings().first()
   event=(await s.execute(text("""SELECT event_id::text event_id,occurred_at,ingested_at,payload
      FROM events WHERE event_type='post_migration.tracking_completed'
        AND payload->>'mint'=:mint
      ORDER BY GREATEST(occurred_at,ingested_at),event_id LIMIT 1"""),
      {"mint":c["mint"]})).mappings().first()
   snaps=[]
   classification={"label":"UNKNOWN","reason":"no_completed_migration_track","evidence_only":True}
   if track and track["migration_at"] is not None and track["completed_at"] is not None:
    snaps=[dict(x) for x in (await s.execute(text("""SELECT captured_at,price_usd,liquidity_usd,volume_m5_usd
       FROM market_snapshots WHERE mint=:mint AND captured_at>=:start AND captured_at<=:end
       ORDER BY captured_at,snapshot_id"""),{"mint":c["mint"],"start":track["migration_at"],"end":track["completed_at"]})).mappings().all()]
    classification=classify_completed_market_path(dict(track),snaps)
   label=str(classification.get("label") or "UNKNOWN").upper()
   if ledger and str(ledger["label"]).upper() in {"RUNNER","HELD","FADE"}:
    state="canonical_ledger_label_available"
   elif launch and str(launch["outcome_status"] or "").upper() in {"RUNNER","HELD","FADE"}:
    state="entity_launch_label_available"
   elif label in {"RUNNER","HELD","FADE"}:
    state="canonical_classification_possible_but_not_reconciled"
   elif not track:
    state="missing_migration_track"
   elif track["status"]!="completed" or track["completed_at"] is None:
    state="migration_track_not_completed"
   else:
    state="canonical_evidence_insufficient"
   details.append({"candidate_id":c["candidate_id"],"mint":c["mint"],"decided_at":c["decided_at"],
    "diagnostic_state":state,"migration_track":dict(track) if track else None,
    "valid_in_window_snapshot_count":len([x for x in snaps if x.get("price_usd") is not None and float(x["price_usd"])>0]),
    "canonical_classifier":classification,"entity_launch":dict(launch) if launch else None,
    "immutable_outcome_ledger":dict(ledger) if ledger else None,
    "tracking_completed_event":dict(event) if event else None})
  summary={}
  for d in details: summary[d["diagnostic_state"]]=summary.get(d["diagnostic_state"],0)+1
 return {"status":"OBSERVED","as_of":datetime.now(timezone.utc).isoformat(),
   "unresolved_count":len(details),"summary":summary,"candidates":details,**AUTH}

async def main():
 print(json.dumps(await diagnose(),sort_keys=True,default=str,indent=2))
 print("[outcome-diagnostic] UNRESOLVED PROSPECTIVE OUTCOMES OBSERVED — read only")
 return 0
if __name__=="__main__": raise SystemExit(asyncio.run(main()))
