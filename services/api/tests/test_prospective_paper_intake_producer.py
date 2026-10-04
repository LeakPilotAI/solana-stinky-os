import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.prospective_paper_intake_producer import (
    PRODUCER_VERSION,
    cohort_signature,
    paper_configuration_from_env,
)

ROOT = Path(__file__).resolve().parents[3]
DB_URL = os.getenv("API_TEST_DATABASE_URL")


def valid_env():
    env = {
        "STINKY_PAPER_POLICY_VERSION": "paper-policy-explicit-v1",
        "STINKY_PAPER_HORIZON": "1h",
        "STINKY_PAPER_MIN_RUNNER_PROBABILITY": "0.50",
        "STINKY_PAPER_MAX_FADE_PROBABILITY": "0.30",
        "STINKY_PAPER_MIN_NONNEGATIVE_MARKET_CAP_PROBABILITY": "0.60",
        "STINKY_PAPER_ENTRY_SLIPPAGE_BPS": "100",
        "STINKY_PAPER_EXIT_SLIPPAGE_BPS": "150",
        "STINKY_PAPER_ENTRY_FEE_BPS": "50",
        "STINKY_PAPER_EXIT_FEE_BPS": "50",
        "STINKY_PAPER_LATENCY_MS": "750",
        "STINKY_PAPER_NOTIONAL_USD": "20",
        "STINKY_PAPER_POLICY_SHA256": "a" * 64,
        "STINKY_PAPER_POLICY_PROVENANCE_JSON": '{"mode":"MANUAL_OPERATOR_SUPPLIED","evidence_backed":false}',
    }

    from stinky_api.paper_policy_provisioning import validate_paper_configuration
    config = paper_configuration_from_env(env)
    env["STINKY_PAPER_POLICY_SHA256"] = validate_paper_configuration(config)["policy_sha256"]
    return env


def test_producer_has_no_hidden_policy_defaults():
    result = paper_configuration_from_env({})
    assert result["configured"] is False
    assert "STINKY_PAPER_POLICY_VERSION" in result["missing"]
    assert "STINKY_PAPER_HORIZON" in result["missing"]
    assert result["live_execution"] is False
    assert result["trading_authority"] is False


def test_explicit_policy_is_accepted_but_hard_caps_notional_at_20():
    result = paper_configuration_from_env(valid_env())
    assert result["configured"] is True
    assert result["paper_notional_usd"] == 20.0
    assert result["policy_sha256"] == valid_env()["STINKY_PAPER_POLICY_SHA256"]
    assert result["provenance"]["evidence_backed"] is False
    too_large = valid_env(); too_large["STINKY_PAPER_NOTIONAL_USD"] = "20.01"
    assert paper_configuration_from_env(too_large)["configured"] is False


def test_cohort_signature_is_versioned_and_contains_no_market_outcome_data():
    sig = cohort_signature("filter-v-test")
    assert sig == {
        "paper_runtime_cohort": "prospective_alert_candidate",
        "producer_version": PRODUCER_VERSION,
        "filter_version": "filter-v-test",
        "source_event_type": "alert.candidate",
    }
    text_sig = repr(sig).lower()
    for forbidden in ("runner", "fade", "held", "exit_price", "future"):
        assert forbidden not in text_sig


def test_source_enforces_prospective_epoch_and_separate_later_close_evidence():
    src = (ROOT / "services/api/src/stinky_api/prospective_paper_intake_producer.py").read_text(encoding="utf-8")
    assert "e.ingested_at >= :started" in src
    assert "decided_at = ingested" in src
    assert '"reference_exit_price"' in src
    assert '"t0_bundle_recomputed": False' in src
    assert "captured_at >= :due" in src
    assert "canonical_sha256(frozen)" in src
    assert "post_migration.tracking_completed" in src
    assert "WOULD_WATCH" in src


def test_launcher_starts_both_prospective_producer_and_paper_worker():
    starter = (ROOT / "scripts/start_paper_runtime.py").read_text(encoding="utf-8")
    supervisor = (ROOT / "scripts/run_genesis_service.py").read_text(encoding="utf-8")
    assert '"paper-intake-producer"' in starter
    assert '"paper-runtime"' in starter
    assert "stinky_api.prospective_paper_policy_runtime" in supervisor
    assert "stinky_api.paper_runtime_worker" in supervisor
    assert "paper-intake-producer" in starter
    forbidden = ("send_transaction", "sign_transaction", "private_key", "solana.rpc")
    corpus = (
        starter
        + (ROOT / "services/api/src/stinky_api/prospective_paper_intake_producer.py").read_text(encoding="utf-8")
        + (ROOT / "services/api/migrations/006_prospective_paper_intake.sql").read_text(encoding="utf-8")
    ).lower()
    assert not any(token in corpus for token in forbidden)


def test_strict_gate_requires_producer_tables_without_changing_executor_contract():
    from scripts import strict_startup_schema_gate as gate
    assert set(gate.REQUIRED_EXECUTOR_TABLES) == {
        "executor_submission_state",
        "executor_submission_transition_audit",
    }
    assert "paper_intake_producer_state" in gate.REQUIRED_PAPER_RUNTIME_TABLES
    assert "paper_prospective_candidate" in gate.REQUIRED_PAPER_RUNTIME_TABLES


pytestmark_pg = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")


async def _apply_006():
    assert DB_URL
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("DROP TABLE IF EXISTS paper_prospective_candidate CASCADE")
        await conn.execute("DROP TABLE IF EXISTS paper_intake_producer_state CASCADE")
        sql = (ROOT / "services/api/migrations/006_prospective_paper_intake.sql").read_text(encoding="utf-8")
        await conn.execute(sql)
    finally:
        await conn.close()


def _factory():
    assert DB_URL
    url = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
@pytestmark_pg
async def test_t0_bundle_cannot_be_rewritten_after_future_data_arrives():
    await _apply_006()
    engine, Session = _factory()
    async with Session() as session:
        await session.execute(text("""
            INSERT INTO paper_prospective_candidate(
                candidate_id,source_event_id,mint,decided_at,
                source_event_occurred_at,source_event_ingested_at,
                producer_version,filter_version,cohort_pattern_hash,
                t0_evidence,t0_evidence_sha256,frozen_bundle,frozen_bundle_sha256,
                reference_entry_price,close_due_at,open_intake_id
            ) VALUES (
                'c1','e1','mint1','2026-09-10T06:00:01Z',
                '2026-09-10T06:00:00Z','2026-09-10T06:00:01Z',
                'prospective-paper-v1','fv1','ph1',
                CAST(:t0 AS jsonb),repeat('a',64),CAST(:frozen AS jsonb),repeat('b',64),
                1.0,'2026-09-10T07:00:01Z','prospective:e1:open'
            )
        """), {"t0": '{"t0":true}', "frozen": '{"frozen":true}'})
        await session.commit()
        with pytest.raises(Exception):
            await session.execute(
                text("UPDATE paper_prospective_candidate SET frozen_bundle=CAST(:payload AS jsonb) WHERE candidate_id='c1'"),
                {"payload": '{"frozen":false}'},
            )
        await session.rollback()
        frozen = (await session.execute(text("SELECT frozen_bundle FROM paper_prospective_candidate WHERE candidate_id='c1'"))).scalar_one()
        assert frozen == {"frozen": True}
    await engine.dispose()


@pytest.mark.asyncio
@pytestmark_pg
async def test_canonical_outcome_and_close_link_are_single_assignment():
    await _apply_006()
    engine, Session = _factory()
    async with Session() as session:
        await session.execute(text("""
            INSERT INTO paper_prospective_candidate(
                candidate_id,source_event_id,mint,decided_at,
                source_event_occurred_at,source_event_ingested_at,
                producer_version,filter_version,cohort_pattern_hash,
                t0_evidence,t0_evidence_sha256
            ) VALUES (
                'c2','e2','mint2','2026-09-10T06:00:01Z',
                '2026-09-10T06:00:00Z','2026-09-10T06:00:01Z',
                'prospective-paper-v1','fv1','ph1',CAST(:t0 AS jsonb),repeat('a',64)
            )
        """), {"t0": '{"t0":true}'})
        await session.execute(text("""
            UPDATE paper_prospective_candidate
            SET canonical_outcome='RUNNER',outcome_observed_at='2026-09-10T07:00:00Z',
                outcome_event_id='oe1',close_intake_id='prospective:e2:close'
            WHERE candidate_id='c2'
        """))
        await session.commit()
        with pytest.raises(Exception):
            await session.execute(text("UPDATE paper_prospective_candidate SET canonical_outcome='FADE' WHERE candidate_id='c2'"))
        await session.rollback()
        with pytest.raises(Exception):
            await session.execute(text("UPDATE paper_prospective_candidate SET close_intake_id='different' WHERE candidate_id='c2'"))
        await session.rollback()
        row = (await session.execute(text("SELECT canonical_outcome,close_intake_id FROM paper_prospective_candidate WHERE candidate_id='c2'"))).one()
        assert tuple(row) == ("RUNNER", "prospective:e2:close")
    await engine.dispose()


def test_prospective_outcomes_consume_later_measured_entity_classification_without_rewriting_t0():
    src = (ROOT / "services/api/src/stinky_api/prospective_paper_intake_producer.py").read_text(encoding="utf-8")
    start = src.index("async def _attach_canonical_outcomes")
    end = src.index("async def _enqueue_due_closes", start)
    block = src[start:end]
    assert "entity_launches" in block
    assert "outcome_meta->>'observed_at'" in block
    assert "canonical_measured_outcome" in block
    assert "migration_tracks" in block
    assert "migration_track:" in block
    assert "classify_completed_market_path" not in block
    assert "canonical_classification" in block
    assert "predictive_authority" in block
    assert "trade_signal" in block
    assert "> c.decided_at" in block
    assert "entity_launches:measured" in block
    assert "WHERE c.canonical_outcome IS NULL" in block
    assert "UPDATE paper_prospective_candidate" in block
    assert "t0_evidence" not in block.split("UPDATE paper_prospective_candidate", 1)[1]
    assert "frozen_bundle" not in block.split("UPDATE paper_prospective_candidate", 1)[1]


def test_policy_identity_is_required_and_frozen_into_bundle_source():
    env=valid_env(); env.pop("STINKY_PAPER_POLICY_SHA256")
    result=paper_configuration_from_env(env)
    assert result["configured"] is False
    assert "STINKY_PAPER_POLICY_SHA256" in result["missing"]
    env=valid_env(); env.pop("STINKY_PAPER_POLICY_PROVENANCE_JSON")
    result=paper_configuration_from_env(env)
    assert result["configured"] is False
    assert "STINKY_PAPER_POLICY_PROVENANCE_JSON" in result["missing"]
    src=(ROOT/"services/api/src/stinky_api/prospective_paper_intake_producer.py").read_text(encoding="utf-8")
    assert '"policy_identity"' in src
    assert '"policy_sha256": config["policy_sha256"]' in src
    assert '"provenance": copy.deepcopy(config["provenance"])' in src
