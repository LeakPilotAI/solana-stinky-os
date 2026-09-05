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
        self.params = []

    async def execute(self, statement, params):
        self.calls += 1
        self.params.append(params)
        if self.calls == 1:
            return Result(first=self.target)
        cutoff = params.get("as_of")
        rows = self.candidates
        if cutoff is not None:
            rows = [row for row in rows if row.get("computed_at") is None or row["computed_at"] <= cutoff]
        return Result(rows=rows)


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
    assert result["outcome_dimensions_excluded"] is True
    assert result["selection_basis"] == "activity_and_network_structure_only"
    assert [row["entity_id"] for row in result["records"]] == ["analogue-1", "analogue-2"]
    assert result["records"][0]["similarity_distance"] == 0.0
    assert "launch_count" in result["records"][0]["matched_dimensions"]
    assert "early_buyer_wallet_count" not in result["records"][0]["matched_dimensions"]
    assert result["records"][0]["evidence_basis"] == "entity_behavior_fingerprints"


@pytest.mark.asyncio
async def test_outcome_only_differences_do_not_change_analogue_distance():
    entity_id = uuid4()
    target = {
        "launch_count": 5,
        "outcomes_known": 5,
        "completed_count": 5,
        "outcomes_unknown": 0,
        "outcome_coverage": 1.0,
        "median_launch_interval_sec": 3600,
        "wallet_count": 2,
        "cadence_bucket": "high_frequency",
    }
    candidate = {
        "entity_id": "analogue-1",
        "fingerprint": {
            "launch_count": 5,
            "outcomes_known": 0,
            "completed_count": 0,
            "outcomes_unknown": 5,
            "outcome_coverage": 0.0,
            "median_launch_interval_sec": 3600,
            "wallet_count": 2,
            "cadence_bucket": "high_frequency",
        },
        "computed_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
    }

    result = await find_historical_analogues(
        Session(target={"fingerprint": target}, candidates=[candidate]),
        entity_id,
    )

    assert result["records"][0]["similarity_distance"] == 0.0
    assert "outcomes_known" not in result["records"][0]["matched_dimensions"]
    assert "completed_count" not in result["records"][0]["matched_dimensions"]
    assert "outcomes_unknown" not in result["records"][0]["matched_dimensions"]
    assert "outcome_coverage" not in result["records"][0]["matched_dimensions"]
    assert result["records"][0]["outcome_dimensions_excluded"] is True


@pytest.mark.asyncio
async def test_analogue_cutoff_is_passed_to_target_and_candidate_queries():
    entity_id = uuid4()
    cutoff = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    session = Session(
        target={"fingerprint": {"launch_count": 2}},
        candidates=[
            {
                "entity_id": "analogue-before-cutoff",
                "fingerprint": {"launch_count": 2},
                "computed_at": datetime(2026, 9, 4, 11, tzinfo=timezone.utc),
            }
        ],
    )

    result = await find_historical_analogues(session, entity_id, as_of=cutoff)

    assert result["as_of"] == cutoff.isoformat()
    assert result["temporal_cutoff_enforced"] is True
    assert session.params[0]["as_of"] == cutoff
    assert session.params[1]["as_of"] == cutoff


@pytest.mark.asyncio
async def test_future_fingerprint_snapshots_are_excluded_by_cutoff():
    entity_id = uuid4()
    cutoff = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    future = datetime(2026, 9, 4, 13, tzinfo=timezone.utc)
    before = datetime(2026, 9, 4, 11, tzinfo=timezone.utc)
    session = Session(
        target={"fingerprint": {"launch_count": 2}},
        candidates=[
            {
                "entity_id": "future-candidate",
                "fingerprint": {"launch_count": 2},
                "computed_at": future,
            },
            {
                "entity_id": "before-candidate",
                "fingerprint": {"launch_count": 2},
                "computed_at": before,
            },
        ],
    )

    result = await find_historical_analogues(session, entity_id, as_of=cutoff)

    assert [row["entity_id"] for row in result["records"]] == ["before-candidate"]
    assert result["temporal_cutoff_enforced"] is True
    assert all(
        datetime.fromisoformat(row["candidate_fingerprint_computed_at"]) <= cutoff
        for row in result["records"]
    )


@pytest.mark.asyncio
async def test_invalid_analogue_cutoff_is_unknown():
    result = await find_historical_analogues(
        Session(target={"fingerprint": {"launch_count": 1}}),
        uuid4(),
        as_of="not-a-timestamp",
    )

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["invalid_as_of"]
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_analogue_discovery_is_unknown_without_target_fingerprint():
    session = Session(target=None)
    result = await find_historical_analogues(session, uuid4())

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["behavior_fingerprint"]
    assert result["evidence_only"] is True
