"""Fail closed on stale active migration tracks; never manufacture completion."""
from __future__ import annotations
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"post-migration-collector"/"src"))
from post_migration.config import settings
from post_migration.store import Store
async def main():
 store=Store()
 try:
  mints=await store.fail_stale_active_tracks(max_duration_sec=settings.track_max_duration_sec)
  print(json.dumps({"status":"OBSERVED","recovered_interrupted_tracks":len(mints),"mints":mints,
   "new_status":"failed","completion_manufactured":False,"paper_only":True,"live_execution":False,
   "trading_authority":False,"rpc_contacted":False,"transaction_signed":False,
   "order_submitted":False,"wallet_mutated":False},sort_keys=True,indent=2))
 finally: await store.close()
 return 0
if __name__=="__main__": raise SystemExit(asyncio.run(main()))
