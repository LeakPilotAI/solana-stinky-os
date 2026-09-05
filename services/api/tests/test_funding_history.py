from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from stinky_api import funding_history


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return FakeResult(self.rows)


@pytest.mark.asyncio
async def test_funding_history_returns_direct_evidence_and_enforces_bounds():
    observed = SimpleNamespace(isoformat=lambda: "2026-09-04T00:00:00+00:00")
    session = FakeSession([{
        "source_wallet": "SOURCE", "destination_wallet": "DESTINATION",
        "amount_lamports": 123456, "signature": "sig-1", "observed_at": observed,
        "created_at": observed,
        "evidence": {"evidence_basis": "direct_transfer_observation"},
    }])

    result = await funding_history.funding_history_for_entity(session, uuid4(), wallet_limit=0, observation_limit=999)

    assert result[0]["source_wallet"] == "SOURCE"
    assert result[0]["destination_wallet"] == "DESTINATION"
    assert result[0]["amount_lamports"] == 123456
    assert result[0]["signature"] == "sig-1"
    assert result[0]["observed_at"] == "2026-09-04T00:00:00+00:00"
    assert result[0]["ingested_at"] == "2026-09-04T00:00:00+00:00"
    assert result[0]["evidence"]["evidence_basis"] == "direct_transfer_observation"
    assert session.calls[0][1]["wallet_limit"] == 1
    assert session.calls[0][1]["observation_limit"] == 500


@pytest.mark.asyncio
async def test_funding_history_no_observations_is_empty():
    session = FakeSession([])
    result = await funding_history.funding_history_for_entity(session, uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_funding_history_passes_temporal_cutoff_to_query():
    session = FakeSession([])
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)
    result = await funding_history.funding_history_for_entity(session, uuid4(), as_of=cutoff)

    assert result == []
    statement, params = session.calls[0]
    assert "wfo.observed_at <= :as_of" in statement
    assert params["as_of"] == cutoff
