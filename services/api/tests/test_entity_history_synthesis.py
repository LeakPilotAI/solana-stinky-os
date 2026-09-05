from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.entity_history_synthesis import synthesize_entity_history


class Result:
    def __init__(self, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first


class Session:
    def __init__(self, launch_rows, fingerprint):
        self.launch_rows = launch_rows
        self.fingerprint = fingerprint
        self.calls = 0

    async def execute(self, statement, params):
        self.calls += 1
        if self.calls == 1:
            return Result(rows=self.launch_rows)
        return Result(first=self.fingerprint)


@pytest.mark.asyncio
async def test_synthesis_combines_independent_evidence_bases_and_bounds():
    entity_id = uuid4()
    observed = datetime(2026, 9, 4, tzinfo=timezone.utc)
    session = Session(
        launch_rows=[
            {
                "id": 7,
                "entity_id": str(entity_id),
                "deployer_wallet": "DEPLOYER",
                "mint": "MINT-1",
                "event_id": "event-1",
                "observed_at": observed,
                "outcome_status": None,
                "outcome_meta": {},
                "created_at": observed,
            }
        ],
        fingerprint={
            "fingerprint": {
                "launch_count": 1,
                "outcomes_unknown": 1,
                "cadence_bucket": "unknown",
                "evidence_basis": "entity_launches+entity_wallets+early_buyer_observations",
            },
            "computed_at": observed,
        },
    )
    graph = {
        "wallets": [{"wallet": "DEPLOYER", "role": "deployer"}],
        "relationships": [
            {
                "wallet_a": "DEPLOYER",
                "wallet_b": "BUYER",
                "relationship_kind": "deployer_buyer_association",
                "observation_count": 1,
            },
        ],
        "bounded": {"wallet_limit": 2, "relationship_limit": 3, "funding_observation_limit": 3},
    }
    funding = [{
        "source_wallet": "SOURCE",
        "destination_wallet": "DEPLOYER",
        "amount_lamports": 123,
        "signature": "sig-1",
        "evidence": {"evidence_basis": "direct_transfer_observation"},
    }]

    result = await synthesize_entity_history(
        session,
        entity_id,
        graph=graph,
        funding_history=funding,
        launch_limit=999,
    )

    assert result["status"] == "KNOWN_ENTITY"
    assert result["evidence_only"] is True
    assert result["entity_id"] == str(entity_id)
    assert result["bounded"]["launch_limit"] == 500
    assert result["launch_history"]["evidence_basis"] == "entity_launches"
    assert result["launch_history"]["records"][0]["outcome_status"] is None
    assert result["behavior_fingerprint"]["fingerprint"]["outcomes_unknown"] == 1
    assert result["wallet_relationships"]["evidence_basis"] == "entity_wallets+wallet_relationships"
    assert result["wallet_relationships"]["records"][0]["relationship_kind"] == "deployer_buyer_association"
    assert result["funding_history"]["evidence_basis"] == "wallet_funding_observations+direct_transfer_observation"
    assert result["funding_history"]["records"][0]["signature"] == "sig-1"


@pytest.mark.asyncio
async def test_missing_behavior_fingerprint_remains_unknown():
    session = Session(launch_rows=[], fingerprint=None)
    result = await synthesize_entity_history(
        session,
        uuid4(),
        graph={"wallets": [], "relationships": [], "bounded": {}},
        funding_history=[],
    )

    assert result["behavior_fingerprint"]["status"] == "UNKNOWN"
    assert result["behavior_fingerprint"]["missing"] == ["behavior_fingerprint"]
    assert result["launch_history"]["status"] == "OBSERVED"
    assert result["launch_history"]["records"] == []
    assert result["funding_history"]["records"] == []
    assert result["evidence_only"] is True
