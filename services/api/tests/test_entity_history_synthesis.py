from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.entity_history_contract import canonicalize_entity_history
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
        self.params = []

    async def execute(self, statement, params):
        self.calls += 1
        self.params.append(params)
        if self.calls == 1:
            return Result(rows=self.launch_rows)
        return Result(first=self.fingerprint)


@pytest.mark.asyncio
async def test_synthesis_combines_independent_evidence_bases_and_bounds():
    entity_id = uuid4()
    observed = datetime(2026, 9, 4, tzinfo=timezone.utc)
    session = Session(
        launch_rows=[{
            "id": 7, "entity_id": str(entity_id), "deployer_wallet": "DEPLOYER",
            "mint": "MINT-1", "event_id": "event-1", "observed_at": observed,
            "outcome_status": None, "outcome_meta": {}, "created_at": observed,
        }],
        fingerprint={
            "fingerprint": {"launch_count": 1, "outcomes_unknown": 1, "cadence_bucket": "unknown",
                            "evidence_basis": "entity_launches+entity_wallets+early_buyer_observations"},
            "computed_at": observed,
        },
    )
    graph = {
        "wallets": [{"wallet": "DEPLOYER", "role": "deployer"}],
        "relationships": [{"wallet_a": "DEPLOYER", "wallet_b": "BUYER",
                            "relationship_kind": "deployer_buyer_association", "observation_count": 1}],
        "bounded": {"wallet_limit": 2, "relationship_limit": 3, "funding_observation_limit": 3},
    }
    funding = [{"source_wallet": "SOURCE", "destination_wallet": "DEPLOYER", "amount_lamports": 123,
                "signature": "sig-1", "observed_at": observed.isoformat(), "ingested_at": observed.isoformat(),
                "evidence": {"evidence_basis": "direct_transfer_observation"}}]

    result = await synthesize_entity_history(session, entity_id, graph=graph, funding_history=funding, launch_limit=999)

    assert result["status"] == "KNOWN_ENTITY"
    assert result["evidence_only"] is True
    assert result["entity_id"] == str(entity_id)
    assert result["bounded"]["launch_limit"] == 500
    assert set(result["sources"]) == {"launch_history", "behavior_fingerprint", "wallet_relationships", "funding_history"}
    assert result["sources"]["launch_history"]["evidence_basis"] == "entity_launches"
    assert result["sources"]["launch_history"]["records"][0]["outcome_status"] is None
    assert result["sources"]["launch_history"]["records"][0]["ingested_at"] == observed.isoformat()
    assert result["sources"]["launch_history"]["provenance"]["observed_at"]["last"] == observed.isoformat()
    assert result["sources"]["launch_history"]["provenance"]["ingested_at"]["last"] == observed.isoformat()
    assert result["sources"]["behavior_fingerprint"]["fingerprint"]["outcomes_unknown"] == 1
    assert result["sources"]["behavior_fingerprint"]["provenance"]["computed_at"] == observed.isoformat()
    assert result["sources"]["behavior_fingerprint"]["provenance"]["freshness_status"] == "UNKNOWN"
    assert result["sources"]["wallet_relationships"]["evidence_basis"] == "entity_wallets+wallet_relationships"
    assert result["sources"]["wallet_relationships"]["records"][0]["relationship_kind"] == "deployer_buyer_association"
    assert result["sources"]["funding_history"]["evidence_basis"] == "wallet_funding_observations+direct_transfer_observation"
    assert result["sources"]["funding_history"]["records"][0]["signature"] == "sig-1"
    assert result["sources"]["funding_history"]["provenance"]["ingested_at"]["last"] == observed.isoformat()
    assert result["missing"] == []


@pytest.mark.asyncio
async def test_missing_behavior_fingerprint_remains_unknown():
    session = Session(launch_rows=[], fingerprint=None)
    result = await synthesize_entity_history(session, uuid4(), graph={"wallets": [], "relationships": [], "bounded": {}}, funding_history=[])

    assert result["sources"]["behavior_fingerprint"]["status"] == "UNKNOWN"
    assert result["missing"] == ["behavior_fingerprint"]
    assert result["sources"]["launch_history"]["status"] == "OBSERVED"
    assert result["sources"]["launch_history"]["records"] == []
    assert result["sources"]["funding_history"]["records"] == []
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_synthesis_passes_temporal_cutoff_to_launch_and_fingerprint_queries():
    entity_id = uuid4()
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)
    session = Session(launch_rows=[], fingerprint=None)

    result = await synthesize_entity_history(
        session, entity_id, graph={"wallets": [], "relationships": [], "bounded": {}},
        funding_history=[], as_of=cutoff,
    )

    assert result["evidence_only"] is True
    assert session.params[0]["as_of"] == cutoff
    assert session.params[1]["as_of"] == cutoff
    assert result["as_of"] == cutoff.isoformat()
    assert result["sources"]["launch_history"]["provenance"]["freshness_status"] == "HISTORICAL_AS_OF"
    assert result["sources"]["behavior_fingerprint"]["provenance"]["freshness_status"] == "HISTORICAL_AS_OF"


def test_canonical_contract_defaults_missing_sources_to_unknown():
    result = canonicalize_entity_history({"status": "KNOWN_ENTITY", "entity_id": "entity-1"})

    assert result["evidence_only"] is True
    assert result["status"] == "KNOWN_ENTITY"
    assert set(result["sources"]) == {"launch_history", "behavior_fingerprint", "wallet_relationships", "funding_history"}
    assert result["missing"] == ["launch_history", "behavior_fingerprint", "wallet_relationships", "funding_history"]
