from datetime import datetime, timezone

import pytest

from stinky_api.pattern_stability_memory import (
    describe_pattern_stability_change,
    pattern_stability_change_feed,
    pattern_stability_hash,
    pattern_stability_history,
)


def _pattern(state="STABLE", *, support=10, early=5, late=5, drift=5.0, dataset="ds1"):
    return {
        "pattern_hash": "p1",
        "pattern_key": "developer.history_state=OBSERVED_HISTORY",
        "feature_tokens": ["developer.history_state=OBSERVED_HISTORY"],
        "stability_status": state,
        "full_support_count": support,
        "early": {"support_count": early, "known_label_coverage": 1.0},
        "late": {"support_count": late, "known_label_coverage": 1.0},
        "outcome_distribution_drift": {"max_drift_pct_points": drift},
        "dataset_hash": dataset,
    }


def test_hash_is_deterministic_for_same_pattern_evidence():
    assert pattern_stability_hash(_pattern()) == pattern_stability_hash(_pattern())


def test_change_detects_stability_transition_and_drift():
    previous = _pattern("STABLE", drift=5.0)
    current = _pattern("UNSTABLE", drift=40.0)
    change = describe_pattern_stability_change(previous, current)
    assert change["status"] == "CHANGED"
    kinds = {c["kind"] for c in change["changes"]}
    assert "STABILITY_STATE_CHANGED" in kinds
    assert "OUTCOME_DRIFT_CHANGED" in kinds
    assert change["predictive_authority"] is False
    assert change["trade_signal"] is False


def test_unknown_state_fails_closed_to_insufficient_evidence():
    current = _pattern("MAGIC")
    initial = describe_pattern_stability_change(None, current)
    assert initial["status"] == "INITIAL_SNAPSHOT"
    assert pattern_stability_hash(current)


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    async def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        rows = self.responses.pop(0) if self.responses else []
        return _Result(rows)


@pytest.mark.asyncio
async def test_history_enforces_dual_as_of_cutoff_and_builds_transition():
    t1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 2, tzinfo=timezone.utc)
    session = _Session([[{
        "id": 2, "pattern_hash": "p1", "evidence_hash": "h2", "evidence": _pattern("UNSTABLE", drift=50.0),
        "observed_at": t2, "ingested_at": t2,
    }, {
        "id": 1, "pattern_hash": "p1", "evidence_hash": "h1", "evidence": _pattern("STABLE", drift=5.0),
        "observed_at": t1, "ingested_at": t1,
    }]])
    result = await pattern_stability_history(session, "p1", as_of=t2)
    sql = session.calls[0][0]
    assert "observed_at <= :as_of AND ingested_at <= :as_of" in sql
    assert result["snapshot_count"] == 2
    assert result["latest_change"]["status"] == "CHANGED"
    assert any(c["kind"] == "STABILITY_STATE_CHANGED" for c in result["latest_change"]["changes"])
    assert result["temporal_cutoff_enforced"] is True


@pytest.mark.asyncio
async def test_change_feed_filters_unchanged_by_default():
    t = datetime(2026, 9, 2, tzinfo=timezone.utc)
    same = _pattern("STABLE")
    session = _Session([[{
        "pattern_hash": "p1", "current_evidence": same, "previous_evidence": same,
        "evidence_hash": "h", "observed_at": t,
    }]])
    result = await pattern_stability_change_feed(session)
    assert result["items"] == []
    assert result["count"] == 0
