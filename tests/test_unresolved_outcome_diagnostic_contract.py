from pathlib import Path
import importlib.util
import os
from unittest.mock import AsyncMock
import pytest
ROOT=Path(__file__).resolve().parents[1]

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
