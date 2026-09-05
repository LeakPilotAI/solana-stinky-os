from datetime import datetime, timezone

import pytest

from entity_resolver.market_outcomes import MarketOutcomeStore, normalize_horizon


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.calls = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(row=self.row, rows=self.rows)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_normalize_horizon_accepts_canonical_values_and_seconds():
    assert normalize_horizon("5m") == ("5m", 300)
    assert normalize_horizon(3600) == ("1h", 3600)
    assert normalize_horizon("unknown") is None
    assert normalize_horizon(True) is None


@pytest.mark.asyncio
async def test_record_observation_preserves_observed_and_ingested_times(monkeypatch):
    store = object.__new__(MarketOutcomeStore)
    observed = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    ingested = datetime(2026, 9, 4, 12, 0, 2, tzinfo=timezone.utc)
    session = FakeSession(row=(1,))
    monkeypatch.setattr(store, "_sessions", lambda: FakeContext(session))

    result = await store.record_observation(
        mint="MINT",
        horizon="5m",
        observed_at=observed,
        ingested_at=ingested,
        metrics={"price_usd": 1.25, "liquidity_usd": 50000},
        source="dexscreener",
        evidence_basis="observed_market_snapshot",
    )

    assert result is True
    assert session.committed is True
    params = session.calls[0][1]
    assert params["observed_at"] == observed
    assert params["ingested_at"] == ingested
    assert params["horizon"] == "5m"
    assert params["horizon_seconds"] == 300
    assert params["source"] == "dexscreener"
    assert params["evidence_basis"] == "observed_market_snapshot"


@pytest.mark.asyncio
async def test_record_observation_rejects_unknown_horizon_without_db_write(monkeypatch):
    store = object.__new__(MarketOutcomeStore)
    session = FakeSession(row=(1,))
    monkeypatch.setattr(store, "_sessions", lambda: FakeContext(session))

    result = await store.record_observation(
        mint="MINT",
        horizon="7m",
        observed_at=datetime.now(timezone.utc),
        source="dexscreener",
        evidence_basis="observed_market_snapshot",
    )

    assert result is False
    assert session.calls == []


@pytest.mark.asyncio
async def test_list_observations_enforces_cutoff_and_bound(monkeypatch):
    store = object.__new__(MarketOutcomeStore)
    session = FakeSession(rows=[])
    monkeypatch.setattr(store, "_sessions", lambda: FakeContext(session))
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)

    result = await store.list_mint_observations(mint="MINT", limit=999, as_of=cutoff)

    assert result == []
    statement, params = session.calls[0]
    assert "observed_at <= :as_of" in statement
    assert params["as_of"] == cutoff
    assert params["limit"] == 500
