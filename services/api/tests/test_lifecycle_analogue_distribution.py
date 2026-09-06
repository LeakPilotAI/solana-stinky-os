from datetime import datetime, timezone

import pytest

from stinky_api.lifecycle_analogue_distribution import load_lifecycle_memories_for_mints, synthesize_lifecycle_distribution
from stinky_api.market_lifecycle_memory import build_market_lifecycle_memory


def _memory(mint, outcome, horizons):
    observations = []
    for name, seconds, metric in horizons:
        observations.append({"mint": mint, "horizon": name, "horizon_seconds": seconds, "anchor_observed_at": "2026-09-01T00:00:00+00:00", "observed_at": "2026-09-01T00:05:00+00:00", "ingested_at": "2026-09-01T00:05:01+00:00", "metrics": {"liquidity_usd": metric}})
    event = {"event_type": "post_migration.tracking_completed", "occurred_at": "2026-09-02T00:00:00+00:00", "ingested_at": "2026-09-02T00:01:00+00:00", "payload": {"mint": mint, "outcome_status": outcome}}
    return build_market_lifecycle_memory(mint=mint, observations=observations, outcome_event=event)


def test_distribution_preserves_unknown_horizons_and_summarizes_numeric_metrics():
    result = synthesize_lifecycle_distribution([
        _memory("A", "RUNNER", [("5m", 300, 10000), ("24h", 86400, 5000)]),
        _memory("B", "FADE", [("5m", 300, 6000)]),
    ])
    assert result["outcome_counts"] == {"RUNNER": 1, "HELD": 0, "FADE": 1, "UNKNOWN": 0}
    five = result["horizons"][0]
    day = result["horizons"][-1]
    assert five["observed_count"] == 2 and five["unknown_count"] == 0
    assert five["metrics"]["liquidity_usd"]["median"] == 8000
    assert day["observed_count"] == 1 and day["unknown_count"] == 1
    assert result["complete_24h_count"] == 0
    assert result["predictive_authority"] is False and result["trade_signal"] is False


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self): self.calls = []
    async def execute(self, statement, params):
        sql = str(statement); self.calls.append((sql, dict(params)))
        if "market_outcome_observations" in sql:
            return _Result([])
        return _Result([])


@pytest.mark.asyncio
async def test_bulk_loader_uses_two_queries_and_dual_temporal_cutoffs():
    session = _Session()
    cutoff = datetime(2026, 9, 3, tzinfo=timezone.utc)
    result = await load_lifecycle_memories_for_mints(session, ["B", "A", "A"], as_of=cutoff, mint_limit=10)
    assert result["bounded"] == {"mint_limit": 10, "mint_count": 2, "query_count": 2}
    assert len(session.calls) == 2
    sql = "\n".join(call[0] for call in session.calls)
    assert "o.observed_at <= :as_of AND o.ingested_at <= :as_of" in sql
    assert "e.occurred_at <= :as_of AND e.ingested_at <= :as_of" in sql
    assert [m["mint"] for m in result["memories"]] == ["A", "B"]
    assert result["temporal_cutoff_enforced"] is True
