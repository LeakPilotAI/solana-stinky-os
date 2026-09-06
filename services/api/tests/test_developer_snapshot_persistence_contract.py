import json

import pytest

from stinky_api.developer_longitudinal_audit import persist_developer_snapshot


class Session:
    def __init__(self): self.calls = []
    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        class Result: pass
        return Result()


@pytest.mark.asyncio
async def test_persisted_snapshot_retains_nested_evidence_for_future_diffs():
    evidence = {
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "history_state": "KNOWN_HISTORY",
        "launch_history": {"historical_launch_count": 2, "outcome_counts": {"RUNNER": 1, "UNKNOWN": 1}},
        "associated_wallets": {"records": [{"wallet": "W1"}]},
        "funding_relationships": {"counterparties": [{"wallet": "F1", "direction": "INBOUND"}]},
        "recurring_early_buyers": {"status": "OBSERVED", "records": [{"wallet": "B1"}]},
    }
    session = Session()
    await persist_developer_snapshot(session, evidence)
    insert = next(params for sql, params in session.calls if "INSERT INTO developer_longitudinal_snapshots" in sql)
    stored = json.loads(insert["evidence"])
    assert stored["launch_history"]["historical_launch_count"] == 2
    assert stored["associated_wallets"]["records"][0]["wallet"] == "W1"
    assert stored["recurring_early_buyers"]["records"][0]["wallet"] == "B1"
