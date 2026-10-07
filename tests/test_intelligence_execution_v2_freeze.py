import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest


def module():
    path = Path(__file__).parents[1] / "scripts/freeze_intelligence_execution_v2.py"
    spec = importlib.util.spec_from_file_location("v2_freeze", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def registry(m):
    p = m.policy()
    return {"policy": json.dumps(p), "policy_sha256": m.policy_hash(p),
            "prospective_boundary": datetime(2026, 10, 7, tzinfo=timezone.utc)}


def test_policy_hash_is_deterministic_and_returned_policy_cannot_mutate_defaults():
    m = module()
    p = m.policy()
    assert m.policy_hash(p) == m.policy_hash(dict(reversed(list(p.items()))))
    p["hold_sec"] = 900
    assert m.policy()["hold_sec"] == 60
    assert m.policy_hash(p) != m.policy_hash(m.policy())


@pytest.mark.parametrize("field,value", [("hold_sec", 120), ("live_execution", True), ("entry_fee_pct", 0), ("adequacy", {})])
def test_registry_rejects_changed_hypothesis_even_with_consistent_hash(field, value):
    m = module()
    row = registry(m)
    p = json.loads(row["policy"])
    p[field] = value
    row.update(policy=p, policy_sha256=m.policy_hash(p))
    with pytest.raises(ValueError, match="frozen_policy_mismatch"):
        m.verify_registry(row)


def test_corrupt_registry_hash_is_rejected():
    m = module()
    row = registry(m)
    row["policy_sha256"] = "0" * 64
    with pytest.raises(ValueError): m.verify_registry(row)


@pytest.mark.asyncio
async def test_refreeze_returns_existing_boundary_and_never_reads_outcomes():
    m = module()
    row = registry(m)
    conn = MagicMock()
    conn.transaction.return_value = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    first = await m.freeze(conn)
    second = await m.freeze(conn)
    assert first == second
    assert first["prospective_boundary"] == row["prospective_boundary"].isoformat()
    assert first["paper_only"] and not first["live_execution"]
    assert all("intelligence_execution_v2_registry" in c.args[0] for c in conn.fetchrow.await_args_list)


@pytest.mark.asyncio
async def test_postgres_registry_is_replay_safe_and_immutable():
    import os
    from uuid import uuid4
    import asyncpg
    url = os.getenv("GENESIS_V2_TEST_DSN")
    if not url:
        pytest.skip("requires isolated GENESIS_V2_TEST_DSN")
    m = module()
    conn = await asyncpg.connect(url)
    schema = "v2_registry_" + uuid4().hex
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        before = await conn.fetchval("SELECT clock_timestamp()")
        first = await m.freeze(conn)
        assert datetime.fromisoformat(first["prospective_boundary"]) >= before
        assert await m.freeze(conn) == first
        assert await conn.fetchval("SELECT count(*) FROM intelligence_execution_v2_registry") == 1
        for sql in ("UPDATE intelligence_execution_v2_registry SET prospective_boundary=now()",
                    "DELETE FROM intelligence_execution_v2_registry", "TRUNCATE intelligence_execution_v2_registry"):
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await conn.execute(sql)
        assert await m.freeze(conn) == first
    finally:
        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await conn.close()
