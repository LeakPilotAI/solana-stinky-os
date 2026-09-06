from datetime import datetime, timezone

import pytest

from stinky_api.historical_research_bridge import (
    historical_research_bridge_preflight,
    recover_historical_research_bridge,
)


class _Mappings:
    def __init__(self, rows):
        self.rows = rows
    def first(self):
        return self.rows[0] if self.rows else None
    def all(self):
        return self.rows


class _ScalarResult:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []
    def scalar(self):
        return self.value
    def mappings(self):
        return _Mappings(self.rows)


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
    async def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    async def commit(self):
        self.commits += 1
    async def rollback(self):
        self.rollbacks += 1


def _table_row():
    return {name: name for name in (
        "migration_tracks", "entity_launches", "entities", "entity_wallets",
        "developer_longitudinal_snapshots", "developer_correlation_snapshots",
        "market_outcome_observations", "events",
    )}


def _preflight_responses(*, bridge_unbridged=7):
    responses = [_ScalarResult(rows=[_table_row()])]
    # 8 factual count queries
    for value in (857, 700, 0, 0, 10, 9, 40, 50):
        responses.append(_ScalarResult(value=value))
    responses.append(_ScalarResult(rows=[{
        "historically_resolvable_migrations": 12,
        "unbridged_historically_resolvable_migrations": bridge_unbridged,
    }]))
    return responses


@pytest.mark.asyncio
async def test_preflight_reports_operational_inventory_and_bridge_gap():
    session = _Session(_preflight_responses())
    result = await historical_research_bridge_preflight(session)
    assert result["status"] == "OBSERVED"
    assert result["counts"]["migration_tracks"] == 857
    assert result["counts"]["entity_launches"] == 0
    assert result["counts"]["unbridged_historically_resolvable_migrations"] == 7
    assert result["bridge_policy"]["future_entity_inference_forbidden"] is True
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_preflight_fails_closed_when_table_probe_fails():
    session = _Session([RuntimeError("db")])
    result = await historical_research_bridge_preflight(session)
    assert result["status"] == "UNKNOWN"
    assert result["failure_stage"] == "table_preflight"
    assert "migration_tracks" in result["missing_tables"]


@pytest.mark.asyncio
async def test_recovery_preserves_migration_observed_time_and_uses_current_ingestion_boundary():
    observed = datetime(2026, 8, 1, tzinfo=timezone.utc)
    created = datetime(2026, 9, 6, tzinfo=timezone.utc)
    responses = _preflight_responses()
    responses.append(_ScalarResult(rows=[{
        "id": 1,
        "mint": "mint1",
        "entity_id": "entity1",
        "deployer_wallet": "creator1",
        "event_id": "migration_bridge:sig1",
        "observed_at": observed,
        "created_at": created,
    }]))
    responses.extend(_preflight_responses(bridge_unbridged=6))
    session = _Session(responses)

    result = await recover_historical_research_bridge(session, limit=100)
    assert result["status"] == "RECOVERED"
    assert result["inserted_count"] == 1
    assert result["records"][0]["observed_at"] == observed.isoformat()
    assert result["records"][0]["created_at"] == created.isoformat()
    assert result["historical_timestamp_preserved"] is True
    assert result["future_entity_inference_forbidden"] is True
    assert result["entity_launch_count_aggregate_modified"] is False
    assert session.commits == 1

    insert_sql = session.calls[10][0]
    assert "x.first_seen_at <= mt.migration_at" in insert_sql
    assert "e.created_at <= mt.migration_at" in insert_sql
    assert "migration_bridge:" in insert_sql
    assert "UPDATE entities" not in insert_sql


@pytest.mark.asyncio
async def test_recovery_is_idempotent_when_no_rows_returned():
    responses = _preflight_responses()
    responses.append(_ScalarResult(rows=[]))
    responses.extend(_preflight_responses(bridge_unbridged=0))
    session = _Session(responses)
    result = await recover_historical_research_bridge(session)
    assert result["status"] == "NO_CHANGE"
    assert result["inserted_count"] == 0
    assert session.commits == 1


@pytest.mark.asyncio
async def test_recovery_rolls_back_and_fails_closed_on_insert_error():
    responses = _preflight_responses()
    responses.append(RuntimeError("insert failed"))
    session = _Session(responses)
    result = await recover_historical_research_bridge(session)
    assert result["status"] == "UNAVAILABLE"
    assert result["inserted_count"] == 0
    assert result["reason"] == "bridge_insert_failed"
    assert session.rollbacks == 1
