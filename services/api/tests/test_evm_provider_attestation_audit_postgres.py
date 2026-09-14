"""Real transaction, replay and append-only enforcement; no external RPCs."""
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api import evm_reference_operator_cli as cli
from stinky_api import evm_reference_observation_trigger as trigger
from stinky_api.evm_provider_attestation_audit import load_provider_attestation_audit
from test_evm_reference_operator_cli import payload


DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL requires API_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_durable_receipt_atomicity_replay_and_mutation_locks(monkeypatch):
    # Own an isolated test schema; never touch production tables or runtime data.
    schema = "test_attestation_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("009_evm_reference_observation_trigger_state.sql", "010_evm_provider_attestation_audit.sql"):
            await conn.execute((migrations / name).read_text())
        engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
                                     connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(cli, "SessionLocal", sessions)
        observers = tuple(SimpleNamespace(
            rpc_url=f"https://rpc-{name}.example/private/SECRET?key=SECRET",
            chain=SimpleNamespace(key="base", chain_id=8453), attest_chain=lambda: 8453,
        ) for name in ("a", "b"))
        monkeypatch.setattr(cli, "build_cli_observers", lambda *args: observers)
        await conn.execute("CREATE TABLE observation_fixture (block_number BIGINT PRIMARY KEY)")
        async def observe(session, **kwargs):
            await session.execute(text("INSERT INTO observation_fixture VALUES (:block)"),
                                  {"block": kwargs["block_number"]})
            return object()
        monkeypatch.setattr(trigger, "observe_and_persist_reference_dex_evidence", observe)

        async def execute(value):
            return await cli.execute_operator_payload(value, rpc_env_vars=("RPC_A", "RPC_B"))

        result = await execute(payload())
        assert result["triggered"] is True
        async with sessions() as session:
            receipt = await load_provider_attestation_audit(session, chain="base",
                pool_address=payload().pool_address, block_number=payload().block_number)
            assert receipt.provider_count == 2
            assert receipt.completed_at.isoformat() == result["state"]["last_completed_at"]
        assert "SECRET" not in await conn.fetchval("SELECT audit_payload::text FROM evm_provider_attestation_audit")
        with pytest.raises(ValueError, match="replay"):
            await execute(payload())
        next_payload = payload().model_copy(update={"block_number": payload().block_number + 1})
        assert (await execute(next_payload))["triggered"] is False  # Not due.
        assert (await execute(next_payload.model_copy(update={"enabled": False})))["triggered"] is False

        # A fresh pool is due. Audit insertion failure must roll back both the
        # observation fixture and the actual completion-state write.
        failing = next_payload.model_copy(update={"pool_address": "0x" + "44" * 20})
        original_append = cli.append_provider_attestation_audit
        async def fail_append(session, record):
            await original_append(session, record)
            raise RuntimeError("after audit insert")
        monkeypatch.setattr(cli, "append_provider_attestation_audit", fail_append)
        with pytest.raises(RuntimeError, match="after audit insert"):
            await execute(failing)
        monkeypatch.setattr(cli, "append_provider_attestation_audit", original_append)

        async def failed_observation(session, **kwargs):
            await observe(session, **kwargs)
            raise RuntimeError("observation failed")
        monkeypatch.setattr(trigger, "observe_and_persist_reference_dex_evidence", failed_observation)
        with pytest.raises(RuntimeError, match="observation failed"):
            await execute(failing)
        for table in ("evm_provider_attestation_audit", "evm_reference_observation_trigger_state", "observation_fixture"):
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 1

        for statement in (
            "UPDATE evm_provider_attestation_audit SET block_number = block_number + 1",
            "DELETE FROM evm_provider_attestation_audit",
            "TRUNCATE evm_provider_attestation_audit",
        ):
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await conn.execute(statement)
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("INSERT INTO evm_provider_attestation_audit SELECT * FROM evm_provider_attestation_audit")
        assert await conn.fetchval("SELECT count(*) FROM evm_provider_attestation_audit") == 1
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute('SET search_path TO public')
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
