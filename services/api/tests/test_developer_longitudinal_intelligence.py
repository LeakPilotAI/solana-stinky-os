from datetime import datetime, timezone
from uuid import uuid4

import pytest

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


def _history():
    return {
        "launch_history": {
            "status": "OBSERVED",
            "records": [
                {"mint": "CURRENT", "observed_at": "2026-09-05T12:00:00+00:00", "outcome_status": "UNKNOWN"},
                {"mint": "PAST-B", "observed_at": "2026-09-04T12:00:00+00:00", "outcome_status": "FADE"},
                {"mint": "PAST-A", "observed_at": "2026-09-03T12:00:00+00:00", "outcome_status": "RUNNER"},
            ],
        }
    }


@pytest.mark.asyncio
async def test_latest_visible_launch_is_reference_and_excluded_from_prior_history():
    session = FakeSession(rows=[{
        "wallet": "BUYER-1",
        "historical_launch_count": 2,
        "best_rank": 2,
        "first_observed_at": datetime(2026, 9, 3, tzinfo=timezone.utc),
        "last_observed_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
        "mints": ["PAST-A", "PAST-B"],
    }])
    entity_id = uuid4()
    graph = {
        "wallets": [{"wallet": "DEV", "role": "deployer", "link_reason": "observed_deployer"}],
        "bounded": {},
    }
    funding = [
        {"source_wallet": "FUNDER", "destination_wallet": "DEV", "observed_at": "2026-09-02T00:00:00+00:00"},
        {"source_wallet": "FUNDER", "destination_wallet": "DEV", "observed_at": "2026-09-03T00:00:00+00:00"},
    ]

    result = await developer_longitudinal_intelligence(
        session,
        entity_id,
        current_mint=None,
        graph=graph,
        history=_history(),
        funding_history=funding,
    )

    assert result["status"] == "OBSERVED"
    assert result["history_state"] == "KNOWN_HISTORY"
    assert result["reference_mint"] == "CURRENT"
    assert result["reference_mint_inferred_from_latest_visible_launch"] is True
    assert result["current_mint_excluded_from_history"] is True
    assert [r["mint"] for r in result["launch_history"]["records"]] == ["PAST-B", "PAST-A"]
    assert result["launch_history"]["outcome_counts"] == {"RUNNER": 1, "HELD": 0, "FADE": 1, "UNKNOWN": 0}
    assert session.params["mints"] == ["PAST-B", "PAST-A"]
    assert result["recurring_early_buyers"]["status"] == "OBSERVED"
    assert result["recurring_early_buyers"]["records"][0]["relationship"] == "REPEAT_HISTORICAL_EARLY_BUYER"
    assert result["recurring_early_buyers"]["records"][0]["coordination_inferred"] is False
    assert result["funding_relationships"]["counterparties"][0]["wallet"] == "FUNDER"
    assert result["funding_relationships"]["counterparties"][0]["observation_count"] == 2
    assert result["funding_relationships"]["ownership_inferred"] is False
    assert result["funding_relationships"]["intent_inferred"] is False


@pytest.mark.asyncio
async def test_fresh_developer_remains_new_unknown_not_good_or_bad():
    result = await developer_longitudinal_intelligence(
        FakeSession(),
        uuid4(),
        current_mint=None,
        graph={"wallets": [{"wallet": "NEW-DEV", "role": "deployer"}]},
        history={"launch_history": {"records": [{"mint": "FIRST", "outcome_status": "UNKNOWN"}]}},
        funding_history=[],
    )

    assert result["history_state"] == "NEW-UNKNOWN"
    assert result["fresh_entity_interpretation"] == "NEW-UNKNOWN"
    assert result["launch_history"]["historical_launch_count"] == 0
    assert result["missing"] == ["prior_developer_launch_history"]
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    for forbidden in ("risk_score", "quality_score", "probability", "confidence", "expected_return"):
        assert forbidden not in result


@pytest.mark.asyncio
async def test_as_of_is_applied_to_repeat_early_buyer_query():
    cutoff = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
    session = FakeSession(rows=[])

    result = await developer_longitudinal_intelligence(
        session,
        uuid4(),
        current_mint="CURRENT",
        graph={"wallets": []},
        history=_history(),
        funding_history=[],
        as_of=cutoff,
    )

    assert session.params["as_of"] == cutoff
    assert "mb.bought_at <= :as_of" in session.sql
    assert result["as_of"] == cutoff.isoformat()
    assert result["temporal_cutoff_enforced"] is True
    assert result["predictive_authority"] is False
