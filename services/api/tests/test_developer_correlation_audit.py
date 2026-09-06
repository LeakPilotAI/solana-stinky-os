from datetime import datetime, timezone

import pytest

from stinky_api.developer_correlation_audit import (
    describe_developer_correlation_change,
    developer_correlation_audit_history,
    developer_correlation_hash,
)


def _evidence(**overrides):
    base = {
        "status": "OBSERVED",
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "wallets": ["dev"],
        "shared_funders": [{"funder_wallet": "f1", "other_entity_id": "e2"}],
        "cross_entity_wallet_reuse": [],
        "deployer_buyer_recurrence": [],
        "shared_relationship_structures": [],
        "missing": [],
    }
    base.update(overrides)
    return base


def test_hash_is_stable_for_non_authority_record_order():
    a = _evidence(shared_funders=[{"funder_wallet": "f2", "other_entity_id": "e3"}, {"funder_wallet": "f1", "other_entity_id": "e2"}])
    b = _evidence(shared_funders=list(reversed(a["shared_funders"])))
    assert developer_correlation_hash(a) == developer_correlation_hash(b)


def test_change_describes_factual_relationship_additions_without_inference():
    previous = _evidence(shared_funders=[])
    current = _evidence(
        shared_funders=[{"funder_wallet": "f1", "other_entity_id": "e2"}],
        cross_entity_wallet_reuse=[{"wallet": "w1", "other_entity_id": "e3"}],
        deployer_buyer_recurrence=[{"wallet": "dev", "buyer_entity_id": "e4"}],
        shared_relationship_structures=[{"relationship_kind": "FUNDED_BY", "other_entity_id": "e5"}],
    )
    result = describe_developer_correlation_change(previous, current)
    kinds = {row["kind"] for row in result["changes"]}
    assert kinds == {"SHARED_FUNDER_ADDED", "WALLET_REUSE_ADDED", "DEPLOYER_BUYER_RECURRENCE_ADDED", "RELATIONSHIP_STRUCTURE_ADDED"}
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_missing_resolution_is_not_called_quality_improvement():
    result = describe_developer_correlation_change(_evidence(missing=["shared_funder_observations"]), _evidence(missing=[]))
    assert result["changes"] == [{"kind": "UNKNOWN_RESOLVED", "fields": ["shared_funder_observations"]}]
    assert "quality" not in str(result["changes"]).lower()


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows=None): self.rows = rows or []
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self, rows): self.rows = rows; self.calls = []
    async def execute(self, statement, params=None):
        sql = str(statement); self.calls.append((sql, params or {}))
        if "SELECT id, entity_id::text" in sql: return _Result(self.rows)
        return _Result()


@pytest.mark.asyncio
async def test_history_as_of_filters_observed_and_ingested_and_retains_exact_hashes():
    ts = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = [{"id": 1, "entity_id": _evidence()["entity_id"], "evidence_hash": "h1", "evidence": _evidence(), "observed_at": ts, "ingested_at": ts}]
    session = _Session(rows)
    result = await developer_correlation_audit_history(session, _evidence()["entity_id"], as_of=ts)
    select_sql, params = next((sql, params) for sql, params in session.calls if "SELECT id, entity_id::text" in sql)
    assert "observed_at <= :as_of" in select_sql
    assert "ingested_at <= :as_of" in select_sql
    assert params["as_of"] == ts
    assert result["records"][0]["evidence_hash"] == "h1"
    assert result["latest_change"]["status"] == "INITIAL_SNAPSHOT"
    assert result["temporal_cutoff_enforced"] is True
