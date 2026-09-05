from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from entity_resolver.relationships import WalletRelationshipStore
from entity_resolver.resolver import co_buy_confidence


def test_co_buy_confidence_is_deterministic_and_descriptive() -> None:
    assert co_buy_confidence(2) == (0.0, "insufficient_overlap")
    assert co_buy_confidence(3) == (0.55, "co_early_buy")
    assert co_buy_confidence(5) == (0.70, "co_early_buy")
    assert co_buy_confidence(8) == (0.85, "strong_co_early_buy")


def test_relationship_contract_contains_evidence_only() -> None:
    forbidden = {"quality_score", "risk_score", "prediction", "buy", "sell", "position_size"}
    relationship = {
        "relationship_kind": "co_early_buy",
        "wallet_a": "A",
        "wallet_b": "B",
        "shared_mints": 5,
        "confidence": 0.70,
        "evidence_basis": "migration_buyers",
    }
    assert forbidden.isdisjoint(relationship)
    assert relationship["evidence_basis"] == "migration_buyers"
    assert relationship["wallet_a"] < relationship["wallet_b"]


def test_deployer_buyer_association_is_factual_and_not_a_prediction() -> None:
    relationship = {
        "relationship_kind": "deployer_buyer_association",
        "wallet_a": "DEPLOYER",
        "wallet_b": "BUYER",
        "observed_mints": 3,
        "confidence": 1.0,
        "evidence_basis": "entity_launches+migration_buyers",
        "confidence_basis": "direct_observed_role_association",
        "first_seen_at": "2026-01-01T00:00:00+00:00",
        "last_seen_at": "2026-01-03T00:00:00+00:00",
    }
    forbidden = {"quality_score", "risk_score", "prediction", "buy", "sell", "position_size"}
    assert forbidden.isdisjoint(relationship)
    assert relationship["evidence_basis"] == "entity_launches+migration_buyers"
    assert relationship["first_seen_at"] < relationship["last_seen_at"]


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, signature_row):
        self.signature_row = signature_row
        self.execute_calls = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement, params=None):
        self.execute_calls.append((str(statement), params or {}))
        if len(self.execute_calls) == 1:
            return _FakeResult(self.signature_row)
        return _FakeResult(None)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_funding_observation_signature_is_durable_idempotency_key() -> None:
    store = WalletRelationshipStore.__new__(WalletRelationshipStore)
    session = _FakeSession(SimpleNamespace(signature="sig-1"))
    store._sessions = lambda: _FakeSessionContext(session)

    recorded = await store.record_funding_observation(
        source_wallet="SOURCE",
        destination_wallet="DESTINATION",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount_lamports=123,
        signature="sig-1",
    )

    assert recorded is True
    assert session.committed is True
    assert session.rolled_back is False
    assert len(session.execute_calls) == 2
    assert "wallet_funding_observations" in session.execute_calls[0][0]
    assert session.execute_calls[0][1]["signature"] == "sig-1"
    assert "wallet_relationships" in session.execute_calls[1][0]


@pytest.mark.asyncio
async def test_duplicate_funding_signature_does_not_increment_relationship() -> None:
    store = WalletRelationshipStore.__new__(WalletRelationshipStore)
    session = _FakeSession(None)
    store._sessions = lambda: _FakeSessionContext(session)

    recorded = await store.record_funding_observation(
        source_wallet="SOURCE",
        destination_wallet="DESTINATION",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount_lamports=123,
        signature="sig-1",
    )

    assert recorded is False
    assert session.committed is False
    assert session.rolled_back is True
    assert len(session.execute_calls) == 1
    assert "wallet_funding_observations" in session.execute_calls[0][0]
