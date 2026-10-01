"""Exercise the accumulation report's real asyncpg query against PostgreSQL."""
import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB_URL=os.getenv("API_TEST_DATABASE_URL")
pytestmark=pytest.mark.skipif(not DB_URL,reason="requires dedicated API_TEST_DATABASE_URL")
ROOT=Path(__file__).resolve().parents[3]

def load_report_module():
    path=ROOT/"scripts"/"report_prospective_evidence_accumulation.py"
    spec=importlib.util.spec_from_file_location("prospective_evidence_report",path)
    module=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

@pytest.mark.asyncio
async def test_report_binds_non_null_prospective_epoch_with_asyncpg():
    schema="evidence_accum_"+uuid4().hex
    conn=await asyncpg.connect(DB_URL)
    engine=None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'''CREATE TABLE "{schema}".paper_intake_producer_state(
          singleton boolean PRIMARY KEY, prospective_started_at timestamptz);
          CREATE TABLE "{schema}".paper_prospective_candidate(
          producer_version text NOT NULL, cohort_pattern_hash text NOT NULL,
          canonical_outcome text, decided_at timestamptz NOT NULL, outcome_observed_at timestamptz);
          CREATE TABLE "{schema}".market_outcome_observations(
          pattern_hash text NOT NULL,horizon text NOT NULL,observed_at timestamptz);''')
        module=load_report_module()
        pattern=module.canonical_pattern_hash(module.cohort_signature(str(module.FILTER_VERSION or "UNKNOWN")))
        started=datetime(2026,9,10,6,29,37,tzinfo=timezone.utc)
        await conn.execute(f'INSERT INTO "{schema}".paper_intake_producer_state VALUES(TRUE,$1)',started)
        await conn.execute(f'''INSERT INTO "{schema}".paper_prospective_candidate
          (producer_version,cohort_pattern_hash,canonical_outcome,decided_at,outcome_observed_at)
          VALUES($1,$2,'RUNNER',$3,$3)''',module.PRODUCER_VERSION,pattern,started)
        await conn.execute(f'''INSERT INTO "{schema}".market_outcome_observations
          (pattern_hash,horizon,observed_at) VALUES($1,'15m',$2)''',pattern,started)
        engine=create_async_engine(DB_URL.replace("postgresql://","postgresql+asyncpg://",1),
          connect_args={"server_settings":{"search_path":schema}})
        module.SessionLocal=async_sessionmaker(engine,expire_on_commit=False)
        result=await module.report()
        assert result["status"]=="OBSERVED"
        assert result["prospective_started_at"]==started
        assert result["counts"]["candidates"]==1
        assert result["counts"]["runners"]==1
        assert result["counts"]["closed"]==1
        assert result["represented_outcome_classes"]==1
        assert result["market_cap_samples_by_horizon"]=={"15m":1}
        assert result["criteria_applied"] is False
        assert result["sufficiency_judgment"] is False
        assert result["automatic_activation"] is False
    finally:
        if engine is not None: await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
