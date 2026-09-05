from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.entity_history_analogues import find_historical_analogues
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
    def __init__(self, launch_rows, fingerprint, candidates=None):
        self.launch_rows = launch_rows
        self.fingerprint = fingerprint
        self.candidates = candidates or []
        self.calls = 0

    async def execute(self, statement, params):
        self.calls += 1
        if self.calls == 1:
            return Result(rows=self.launch_rows)
        if self.calls == 2:
            return Result(first=self.fingerprint)
        if self.calls == 3:
            return Result(first=self.fingerprint)
        return Result(rows=self.candidates)


@pytest.mark.asyncio
async def test_synthesis_combines_independent_evidence_bases_and_bounds():
    entity_id = uuid4()
    observed = datetime(2026, 9, 4, tzinfo=timezone.utc)
    fingerprint = {
        "launch_count": 1,
        "outcomes_unknown": 1,
        "cadence_bucket": "unknown",
        "evidence_basis": "entity_launches+entity_wallets+early_buyer_observations",
    }
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
        fingerprint={"fingerprint": fingerprint, "computed_at": observed},
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
    assert set(result["sources"]) == {
        "launch_history",
        "behavior_fingerprint",
        "wallet_relationships",
        "funding_history",
        "historical_analogues",
    }
    assert result["sources"]["launch_history"]["evidence_basis"] == "entity_launches"
    assert result["sources"]["launch_history"]["records"][0]["outcome_status"] is None
    assert result["sources"]["behavior_fingerprint"]["fingerprint"]["outcomes_unknown"] == 1
    assert result["sources"]["wallet_relationships"]["evidence_basis"] == "entity_wallets+wallet_relationships"
    assert result["sources"]["wallet_relationships"]["records"][0]["relationship_kind"] == "deployer_buyer_association"
    assert result["sources"]["funding_history"]["evidence_basis"] == "wallet_funding_observations+direct_transfer_observation"
    assert result["sources"]["funding_history"]["records"][0]["signature"] == "sig-1"
    assert result["sources"]["historical_analogues"]["status"] == "OBSERVED_EMPTY"
    assert result["missing"] == []


@pytest.mark.asyncio
async def test_missing_behavior_fingerprint_remains_unknown():
    session = Session(launch_rows=[], fingerprint=None)
    result = await synthesize_entity_history(
        session,
        uuid4(),
        graph={"wallets": [], "relationships": [], "bounded": {}},
        funding_history=[],
    )

    assert result["sources"]["behavior_fingerprint"]["status"] == "UNKNOWN"
    assert result["missing"] == ["behavior_fingerprint"]
    assert result["sources"]["launch_history"]["status"] == "OBSERVED"
    assert result["sources"]["launch_history"]["records"] == []
    assert result["sources"]["funding_history"]["records"] == []
    assert result["sources"]["historical_analogues"]["status"] == "UNKNOWN"
    assert result["evidence_only"] is True


def test_canonical_contract_defaults_missing_sources_to_unknown():
    result = canonicalize_entity_history({"status": "KNOWN_ENTITY", "entity_id": "entity-1"})

    assert result["evidence_only"] is True
    assert result["status"] == "KNOWN_ENTITY"
    assert set(result["sources"]) == {
        "launch_history",
        "behavior_fingerprint",
        "wallet_relationships",
        "funding_history",
        "historical_analogues",
    }
    assert result["missing"] == [
        "launch_history",
        "behavior_fingerprint",
        "wallet_relationships",
        "funding_history",
        "historical_analogues",
    ]


@pytest.mark.asyncio
async def test_historical_analogues_are_descriptive_and_preserve_missing_dimensions():
    entity_id = uuid4()
    target = {
        "launch_count": 5,
        "outcomes_known": 2,
        "completed_count": 1,
        "outcomes_unknown": 3,
        "outcome_coverage": 0.4,
        "median_launch_interval_sec": 3600,
        "wallet_count": 3,
        "early_buyer_wallet_count": None,
        "early_buyer_mint_count": None,
        "repeat_early_buyer_wallet_count": None,
        "cadence_bucket": "high_frequency",
    }
    session = Session(
        launch_rows=[],
        fingerprint=target,
        candidates=[
            {
                "entity_id": "analogue-1",
                "fingerprint": {
                    "launch_count": 5,
                    "outcomes_known": 2,
                    "completed_count": 1,
                    "outcomes_unknown": 3,
                    "outcome_coverage": 0.4,
                    "median_launch_interval_sec": 3600,
                    "wallet_count": 3,
                    "cadence_bucket": "high_frequency",
                },
                "computed_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
            },
            {
                "entity_id": "analogue-2",
                "fingerprint": {"launch_count": 50, "cadence_bucket": "sparse"},
                "computed_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
            },
        ],
    )

    result = await find_historical_analogues(session, entity_id, limit=10, candidate_limit=500)

    assert result["status"] == "OBSERVED"
    assert result["evidence_only"] is True
    assert [row["entity_id"] for row in result["records"]] == ["analogue-1", "analogue-2"]
    assert result["records"][0]["similarity_distance"] == 0.0
    assert "launch_count" in result["records"][0]["matched_dimensions"]
    assert "early_buyer_wallet_count" not in result["records"][0]["matched_dimensions"]
    assert result["records"][0]["evidence_basis"] == "entity_behavior_fingerprints"


@pytest.mark.asyncio
async def test_analogue_discovery_is_unknown_without_target_fingerprint():
    session = Session(launch_rows=[], fingerprint=None)
    result = await find_historical_analogues(session, uuid4())

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["behavior_fingerprint"]
    assert result["evidence_only"] is not True
