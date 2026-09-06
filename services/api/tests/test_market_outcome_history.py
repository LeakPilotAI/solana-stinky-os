from datetime import datetime, timezone

import pytest

from stinky_api.market_outcome_history import market_lifecycle_for_mint


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
async def test_market_lifecycle_returns_bounded_observations():
    observed = datetime(2026, 9, 4, tzinfo=timezone.utc)
    session = FakeSession([{
        "id": 1,
        "mint": "MINT",
        "horizon": "5m",
        "horizon_seconds": 300,
        "anchor_observed_at": observed,
        "observed_at": observed,
        "ingested_at": observed,
        "source": "market_snapshots",
        "evidence_basis": "market_snapshot_observation",
        "metrics": {"price_usd": 1.25},
        "event_id": None,
        "signature": None,
        "created_at": observed,
    }])

    result = await market_lifecycle_for_mint(session, "MINT", limit=999)

    assert result["status"] == "OBSERVED"
    assert result["mint"] == "MINT"
    assert result["records"][0]["horizon"] == "5m"
    assert result["records"][0]["observed_at"] == observed.isoformat()
    assert result["evidence_only"] is True
    assert result["bounded"]["limit"] == 500
    assert session.calls[0][1]["limit"] == 500


@pytest.mark.asyncio
async def test_market_lifecycle_enforces_as_of_cutoff():
    session = FakeSession([])
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)

    result = await market_lifecycle_for_mint(session, "MINT", as_of=cutoff)

    statement, params = session.calls[0]
    assert "observed_at <= :as_of" in statement
    assert params["as_of"] == cutoff
    assert result["status"] == "UNKNOWN"
    assert result["as_of"] == cutoff.isoformat()
    assert result["temporal_cutoff_enforced"] is True
    assert result["missing"] == ["market_outcome_observations"]


@pytest.mark.asyncio
async def test_invalid_as_of_is_unknown():
    session = FakeSession([])
    result = await market_lifecycle_for_mint(session, "MINT", as_of="not-a-timestamp")

    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]
    assert session.calls == []
