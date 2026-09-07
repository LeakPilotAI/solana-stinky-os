from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.developer_longitudinal_audit import (
    describe_developer_change,
    developer_evidence_hash,
)
from stinky_api.developer_longitudinal_intelligence import developer_longitudinal_intelligence


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.sql = ""
        self.params = None

    async def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params
        return _Result(self.rows)


def _evidence(mints):
    records = [
        {
            "mint": mint,
            "observed_at": f"2026-09-0{index + 1}T12:00:00+00:00",
            "outcome_status": "UNKNOWN",
        }
        for index, mint in enumerate(mints)
    ]
    return {
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "reference_mint": "CURRENT",
        "history_state": "KNOWN_HISTORY" if records else "NEW-UNKNOWN",
        "repeat_deployer": {
            "status": "OBSERVED" if records else "UNKNOWN",
            "prior_launch_count": len(records),
        },
        "launch_history": {
            "historical_launch_count": len(records),
            "records": records,
            "outcome_counts": {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": len(records)},
        },
        "associated_wallets": {
            "records": [
                {"wallet": "W2", "role": "deployer"},
                {"wallet": "W1", "role": "associated"},
            ]
        },
        "funding_relationships": {
            "counterparties": [
                {
                    "wallet": "F1",
                    "direction": "INBOUND",
                    "observation_count": 2,
                    "first_observed_at": "2026-09-01T00:00:00+00:00",
                    "last_observed_at": "2026-09-02T00:00:00+00:00",
                }
            ]
        },
        "recurring_early_buyers": {
            "status": "OBSERVED",
            "records": [
                {
                    "wallet": "B1",
                    "historical_launch_count": 2,
                    "mints": sorted(mints),
                    "relationship": "REPEAT_HISTORICAL_EARLY_BUYER",
                }
            ],
        },
    }


def test_semantic_hash_changes_when_launch_identity_changes_even_if_counts_match():
    first = _evidence(["PAST-A", "PAST-B"])
    second = _evidence(["PAST-A", "PAST-C"])

    assert first["launch_history"]["historical_launch_count"] == second["launch_history"]["historical_launch_count"]
    assert first["launch_history"]["outcome_counts"] == second["launch_history"]["outcome_counts"]
    assert developer_evidence_hash(first) != developer_evidence_hash(second)

    change = describe_developer_change(first, second)
    assert change["status"] == "CHANGED"
    launch_set = next(item for item in change["changes"] if item["kind"] == "LAUNCH_SET_CHANGED")
    assert launch_set["added"] == ["PAST-C"]
    assert launch_set["removed"] == ["PAST-B"]
    assert change["risk_inferred"] is False
    assert change["quality_inferred"] is False
    assert change["predictive_authority"] is False
    assert change["trade_signal"] is False


def test_semantic_hash_is_order_stable_for_equivalent_evidence():
    first = _evidence(["PAST-A", "PAST-B"])
    second = _evidence(["PAST-B", "PAST-A"])
    second["launch_history"]["records"] = list(reversed(first["launch_history"]["records"]))
    second["associated_wallets"]["records"] = list(reversed(first["associated_wallets"]["records"]))
    second["recurring_early_buyers"]["records"][0]["mints"] = ["PAST-B", "PAST-A"]

    assert developer_evidence_hash(first) == developer_evidence_hash(second)
    assert describe_developer_change(first, second)["status"] == "UNCHANGED"


@pytest.mark.asyncio
async def test_as_of_fail_closed_excludes_future_and_timestamp_less_launches_and_funding():
    cutoff = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
    history = {
        "launch_history": {
            "records": [
                {"mint": "FUTURE", "observed_at": "2026-09-05T12:00:00+00:00", "outcome_status": "RUNNER"},
                {"mint": "CURRENT", "observed_at": "2026-09-04T12:00:00+00:00", "outcome_status": "UNKNOWN"},
                {"mint": "PAST", "observed_at": "2026-09-03T12:00:00+00:00", "outcome_status": "FADE"},
                {"mint": "NO-TIME", "outcome_status": "RUNNER"},
            ]
        }
    }
    funding = [
        {"source_wallet": "F-PAST", "destination_wallet": "DEV", "observed_at": "2026-09-03T00:00:00+00:00"},
        {"source_wallet": "F-FUTURE", "destination_wallet": "DEV", "observed_at": "2026-09-05T00:00:00+00:00"},
        {"source_wallet": "F-NO-TIME", "destination_wallet": "DEV"},
    ]

    result = await developer_longitudinal_intelligence(
        FakeSession(rows=[]),
        uuid4(),
        current_mint="CURRENT",
        graph={"wallets": [{"wallet": "DEV", "role": "deployer"}]},
        history=history,
        funding_history=funding,
        as_of=cutoff,
    )

    assert [row["mint"] for row in result["launch_history"]["records"]] == ["PAST"]
    assert result["launch_history"]["historical_launch_count"] == 1
    assert result["repeat_deployer"]["status"] == "OBSERVED"
    assert result["repeat_deployer"]["prior_launch_count"] == 1
    assert result["repeat_deployer"]["derived_from_observed_prior_launches_only"] is True
    assert result["funding_relationships"]["observation_count"] == 1
    assert result["funding_relationships"]["counterparties"][0]["wallet"] == "F-PAST"
    assert result["temporal_input_filtering"] == {
        "cutoff_enforced": True,
        "launch_rows_excluded": 2,
        "funding_rows_excluded": 2,
        "missing_or_invalid_timestamps_fail_closed": True,
    }
    assert result["temporal_cutoff_enforced"] is True
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_future_only_history_cannot_upgrade_fresh_developer_at_cutoff():
    cutoff = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
    result = await developer_longitudinal_intelligence(
        FakeSession(),
        uuid4(),
        current_mint="CURRENT",
        graph={"wallets": [{"wallet": "DEV", "role": "deployer"}]},
        history={
            "launch_history": {
                "records": [
                    {"mint": "CURRENT", "observed_at": "2026-09-04T12:00:00+00:00", "outcome_status": "UNKNOWN"},
                    {"mint": "FUTURE", "observed_at": "2026-09-05T12:00:00+00:00", "outcome_status": "RUNNER"},
                ]
            }
        },
        funding_history=[],
        as_of=cutoff,
    )

    assert result["history_state"] == "NEW-UNKNOWN"
    assert result["fresh_entity_interpretation"] == "NEW-UNKNOWN"
    assert result["repeat_deployer"]["status"] == "UNKNOWN"
    assert result["repeat_deployer"]["prior_launch_count"] == 0
    assert result["missing"] == ["prior_developer_launch_history"]
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
