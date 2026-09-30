"""Exercise the real migrations/query/adapter/evaluator against isolated PostgreSQL."""
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.paper_cohort_report import report_paper_cohort
from test_paper_cohort_report import row, selection, criteria

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="requires dedicated API_TEST_DATABASE_URL")


async def insert(session, value):
    await session.execute(text("""
        INSERT INTO paper_runtime_intake(intake_id,mint,observed_at,created_at,payload,payload_sha256)
        VALUES (:intake_id,:mint,CAST(:observed_at AS timestamptz),CAST(:intake_created_at AS timestamptz),
                CAST(:payload AS jsonb),:payload_sha256)
    """), {**value, "payload": json.dumps(value["payload"])})
    await session.execute(text("""
        INSERT INTO paper_runtime_record(intake_id,mint,decided_at,created_at,shadow_status,paper_status,
                                        policy_version,policy_sha256,policy_evidence_backed,record)
        VALUES (:intake_id,:mint,CAST(:decided_at AS timestamptz),CAST(:created_at AS timestamptz),
                'SHADOW_DECISION',:paper_status,:policy_version,:policy_sha256,:policy_evidence_backed,CAST(:record AS jsonb))
    """), {**value, "record": json.dumps(value["record"])})


@pytest.mark.asyncio
async def test_database_selection_cutoff_identity_and_overflow_are_fail_closed():
    schema = "cohort_test_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("005_paper_runtime.sql", "013_paper_runtime_policy_identity.sql", "014_paper_cohort_report.sql", "014_paper_cohort_report.sql"):
            await conn.execute((migrations / name).read_text())
        # No active registry exists: selection must be entirely historical.
        engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
                                     connect_args={"server_settings": {"search_path": schema}})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await insert(session, row())
            await insert(session, row("other-policy", sha="b" * 64, version="other", backed=True))
            legacy = row("legacy"); legacy.update(policy_sha256=None, policy_version=None, policy_evidence_backed=None)
            await insert(session, legacy)
            future = row("future", at="2026-09-12T00:00:00Z")
            await insert(session, future)
            await session.commit()
            report = await report_paper_cohort(session, **selection(), release_criteria=criteria())
            assert report["status"] == "OBSERVED"
            assert report["counts"]["total_immutable_records"] == 1
            assert report["walk_forward_evaluated"] is True
            assert report["walk_forward"]["evaluated_records"][0]["intake_id"] == "close-1"
            absent = await report_paper_cohort(session, **selection(policy_sha256="c" * 64))
            assert absent["reasons"] == ["selected_cohort_not_found_as_of"]
            truncated = await report_paper_cohort(session, **selection(as_of="2026-09-13T00:00:00Z", record_limit=1))
            assert truncated["reasons"] == ["cohort_exceeds_record_limit"]
            # Same SHA with a different version cannot be hidden by SQL filtering.
            await insert(session, row("conflict", version="conflicting-version"))
            await session.commit()
            conflict = await report_paper_cohort(session, **selection(), release_criteria=criteria())
            assert conflict["reasons"] == ["stored_policy_identity_mismatch"]
            assert conflict["walk_forward"] is None
            with pytest.raises(Exception):
                await session.execute(text("UPDATE paper_runtime_record SET policy_version='relabelled'"))
            await session.rollback()
            index = (await session.execute(text("SELECT indexdef FROM pg_indexes WHERE schemaname=:schema AND indexname='idx_paper_runtime_record_cohort_report'"), {"schema": schema})).scalar_one()
            assert "(policy_sha256, created_at, intake_id)" in index
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
