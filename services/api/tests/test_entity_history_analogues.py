from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.entity_history_analogues import find_historical_analogues


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
    def __init__(self, target, candidates=None):
        self.target = target
        self.candidates = candidates or []
        self.calls = 0

    async def execute(self, statement, params):
        self.calls += 1
        if self.calls == 1:
            return Result(first=self.target)
        return Result(rows=self.candidates)


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
        target={"fingerprint": target},
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
    session = Session(target=None)
    result = await find_historical_analogues(session, uuid4())

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["behavior_fingerprint"]
    assert result["evidence_only"] is True
