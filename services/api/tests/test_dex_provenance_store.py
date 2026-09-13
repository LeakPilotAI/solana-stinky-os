from datetime import datetime, timezone
from pathlib import Path

import pytest

from stinky_api.dex_provenance_store import (
    append_dex_provenance_evidence,
    load_latest_dex_provenance_evidence,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Mappings:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return _Mappings(self.row)


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_append_is_identity_scoped_and_idempotent():
    session = _Session([_ScalarResult(None), _ScalarResult(17)])
    row_id = await append_dex_provenance_evidence(
        session,
        chain=" base ",
        pool_address=" 0xpool ",
        evidence_block=123,
        evidence_key="sha256:abc",
        record_payload={"status": "UNVERIFIED_REFERENCE_DEX_EVIDENCE_RECORD"},
        sources_payload=({"contract_role": "FACTORY"},),
    )
    assert row_id == 17
    assert session.calls[0][1]["chain"] == "base"
    assert session.calls[0][1]["pool_address"] == "0xpool"
    assert "ON CONFLICT" in session.calls[0][0]
    assert "UPDATE" not in session.calls[0][0].upper()


@pytest.mark.asyncio
async def test_load_latest_preserves_record_and_source_payloads():
    observed = datetime(2026, 9, 13, tzinfo=timezone.utc)
    record = {"status": "UNVERIFIED_REFERENCE_DEX_EVIDENCE_RECORD", "relationship": {"block_number": 123}}
    sources = [{"contract_role": "FACTORY", "source_commit": "a" * 40}]
    session = _Session([_MappingResult({
        "id": 9,
        "chain": "base",
        "pool_address": "0xpool",
        "evidence_block": 123,
        "evidence_key": "sha256:abc",
        "record_payload": record,
        "sources_payload": sources,
        "observed_at": observed,
    })])
    loaded = await load_latest_dex_provenance_evidence(session, chain="base", pool_address="0xpool")
    assert loaded is not None
    assert loaded.record_payload is record
    assert loaded.sources_payload == tuple(sources)
    assert loaded.evidence_block == 123
    assert loaded.observed_at is observed
    assert "ORDER BY evidence_block DESC, id DESC" in session.calls[0][0]


@pytest.mark.asyncio
async def test_load_missing_evidence_stays_missing():
    session = _Session([_MappingResult(None)])
    assert await load_latest_dex_provenance_evidence(session, chain="base", pool_address="0xpool") is None


@pytest.mark.asyncio
async def test_store_rejects_malformed_or_missing_identity():
    session = _Session([])
    with pytest.raises(ValueError, match="chain required"):
        await load_latest_dex_provenance_evidence(session, chain=" ", pool_address="0xpool")
    with pytest.raises(ValueError, match="evidence_block"):
        await append_dex_provenance_evidence(
            session,
            chain="base",
            pool_address="0xpool",
            evidence_block=-1,
            evidence_key="key",
            record_payload={},
            sources_payload=(),
        )


def test_migration_enforces_append_only_evidence_history():
    migration = Path(__file__).parents[1] / "migrations" / "008_dex_provenance_evidence.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "dex_provenance_evidence_snapshots" in sql
    assert "record_payload JSONB NOT NULL" in sql
    assert "sources_payload JSONB NOT NULL" in sql
    assert "BEFORE UPDATE" in sql
    assert "BEFORE DELETE" in sql
    assert "append-only" in sql
