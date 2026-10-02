from pathlib import Path
import importlib.util
import os
from unittest.mock import AsyncMock
from unittest.mock import MagicMock, Mock
from datetime import datetime, timedelta, timezone
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
@pytest.mark.parametrize("status,has_end,valid_path,expected",[
 ("failed",True,True,"UNKNOWN"),
 ("interrupted",True,True,"UNKNOWN"),
 ("active",True,True,"UNKNOWN"),
 ("active",False,True,"UNKNOWN"),
 ("completed",False,True,"UNKNOWN"),
 ("completed",True,True,"RUNNER"),
 ("completed",True,False,"UNKNOWN"),
])
async def test_diagnostic_classifies_only_completed_tracks(monkeypatch,status,has_end,valid_path,expected):
 module=_diagnostic_module()
 start=datetime(2026,10,2,tzinfo=timezone.utc)
 candidate={"candidate_id":"candidate","source_event_id":"legacy-id","mint":"fixture","decided_at":start}
 track={"track_id":"track","migration_at":start,"completed_at":start+timedelta(seconds=3600) if has_end else None,"status":status}
 snapshots=[{"captured_at":start+timedelta(seconds=30),"price_usd":1,"liquidity_usd":100,"volume_m5_usd":100},
            {"captured_at":start+timedelta(seconds=3590),"price_usd":3,"liquidity_usd":100,"volume_m5_usd":100}] if valid_path else []
 async def execute(statement,*args):
  sql=str(statement)
  assert sql.lstrip().startswith("SELECT")
  result=MagicMock()
  result.mappings.return_value.first.return_value=track if "FROM migration_tracks" in sql else None
  result.mappings.return_value.all.return_value=[candidate] if "FROM paper_prospective_candidate" in sql else snapshots
  return result
 session=AsyncMock()
 session.__aenter__.return_value=session
 session.execute.side_effect=execute
 monkeypatch.setattr(module,"SessionLocal",lambda:session)
 classifier=Mock(wraps=module.classify_completed_market_path)
 monkeypatch.setattr(module,"classify_completed_market_path",classifier)
 result=await module.diagnose()
 detail=result["candidates"][0]
 assert detail["canonical_classifier"]["label"]==expected
 assert classifier.call_count==(1 if status=="completed" and has_end else 0)
 if status=="failed":
  assert detail["diagnostic_state"]=="migration_track_failed_or_interrupted"
 elif status!="completed" or not has_end:
  assert detail["diagnostic_state"]=="migration_track_not_completed"
 elif not valid_path:
  assert detail["diagnostic_state"]=="canonical_evidence_insufficient"
 assert result["read_only"] and not result["candidate_mutated"]
 assert not result["live_execution"] and not result["trading_authority"]
 session.commit.assert_not_awaited()
 session.flush.assert_not_awaited()

def _diagnostic_module():
 spec=importlib.util.spec_from_file_location("unresolved_diagnostic",ROOT/"scripts"/"diagnose_unresolved_prospective_outcomes.py")
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 return module

@pytest.mark.asyncio
@pytest.mark.parametrize("source_id",[None,"","legacy-source","not-a-uuid","00000000000040008000000000000001"])
async def test_invalid_legacy_source_is_absent_without_database_failure(source_id):
 session=AsyncMock()
 assert await _diagnostic_module().source_event_for_candidate(session,source_id) is None
 session.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_source_lookup_preserves_evidence_and_uses_uuid_index():
 from sqlalchemy import text
 from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
 url=os.environ.get("API_TEST_DATABASE_URL")
 if not url:
  pytest.skip("requires isolated CI PostgreSQL")
 engine=create_async_engine(url.replace("postgresql://","postgresql+asyncpg://",1))
 try:
  async with engine.connect() as conn:
   await conn.execute(text("""CREATE TEMP TABLE events (
     event_id uuid, event_type text, occurred_at timestamptz, ingested_at timestamptz,
     signature text, producer text, payload jsonb, PRIMARY KEY(event_id,occurred_at))"""))
   await conn.execute(text("""INSERT INTO events VALUES
    ('00000000-0000-4000-8000-000000000001','alert.candidate','2026-10-02T00:00:00Z','2026-10-02T00:00:00Z','sig','sentinel','{"mint":"fixture"}'),
    ('00000000-0000-4000-8000-000000000001','alert.candidate','2026-10-03T00:00:00Z','2026-10-03T00:00:00Z','later','sentinel','{}')"""))
   await conn.commit()
   async with AsyncSession(bind=conn) as session:
    module=_diagnostic_module()
    captured=[]
    original=session.execute
    async def record(statement,parameters):
     captured.append((statement,parameters))
     return await original(statement,parameters)
    session.execute=record
    found=await module.source_event_for_candidate(session,"00000000-0000-4000-8000-000000000001")
    assert found["signature"]=="sig"
    assert found["payload"]=={"mint":"fixture"}
    assert await module.source_event_for_candidate(session,"00000000-0000-4000-8000-000000000002") is None
    # Force the planner to expose whether the existing UUID index is usable.
    await conn.execute(text("SET LOCAL enable_seqscan=off"))
    statement,parameters=captured[0]
    plan=(await conn.execute(text("EXPLAIN (FORMAT JSON) "+str(statement)),parameters)).scalar_one()
    def uses_identity_index(node):
     return ("Index Cond" in node and "event_id" in node["Index Cond"]) or any(uses_identity_index(x) for x in node.get("Plans",[]))
    assert uses_identity_index(plan[0]["Plan"])
 finally:
  await engine.dispose()
def test_unresolved_diagnostic_reuses_canonical_classifier_and_is_read_only():
 t=(ROOT/"scripts"/"diagnose_unresolved_prospective_outcomes.py").read_text()
 assert "classify_completed_market_path" in t
 assert "entity_launch_outcome_labels" in t
 assert "migration_tracks" in t
 assert "market_snapshots" in t
 assert "post_migration.tracking_completed" in t
 for x in ['"read_only":True','"candidate_mutated":False','"automatic_activation":False','"classification_reused":True']:
  assert x in t
 low=t.lower()
 for forbidden in ("update paper_prospective_candidate","insert into paper_prospective_candidate","record_outcome(","provision_paper_policy","send_transaction","private_key"):
  assert forbidden not in low
def test_unresolved_diagnostic_has_explicit_evidence_states():
 t=(ROOT/"scripts"/"diagnose_unresolved_prospective_outcomes.py").read_text()
 for x in ("canonical_ledger_label_available","entity_launch_label_available","canonical_classification_possible_but_not_reconciled","missing_migration_track","migration_track_not_completed","canonical_evidence_insufficient"):
  assert x in t
def test_unresolved_diagnostic_launcher_starts_only_postgres():
 t=(ROOT/"Run-Unresolved-Outcome-Diagnostic.cmd").read_text()
 assert "docker compose -p project-genesis up -d postgres" in t
 assert "diagnose_unresolved_prospective_outcomes.py" in t
 assert "Start-Stinky-OS" not in t
