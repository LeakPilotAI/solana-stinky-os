from datetime import datetime, timezone

import pytest

from stinky_api.developer_relationship_stability import (
    assess_developer_relationship_stability,
    developer_relationship_stability,
)


def _rel(kind="SHARED_FUNDER", wallet="F1", other="E2"):
    return {"kind": kind, "identity": {"funder_wallet": wallet, "other_entity_id": other},
            "independent_observation_count": 2, "repetition_state": "REPEATED_OBSERVATION"}


def _snap(i, day, relationships):
    return {"id": i, "evidence_hash": f"h{i}",
            "observed_at": f"2026-08-{day:02d}T00:00:00+00:00",
            "ingested_at": f"2026-08-{day:02d}T01:00:00+00:00",
            "evidence": {"repetition_analysis": {"records": relationships}}}


def test_exact_relationship_recurrence_across_windows_is_stable():
    rel = _rel()
    result = assess_developer_relationship_stability([
        _snap(1, 1, [rel]), _snap(2, 5, [rel]), _snap(3, 10, [rel]), _snap(4, 15, [rel])
    ])
    assert result["stability_status"] == "STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["cross_window_recurrent_count"] == 1
    assert result["records"][0]["recurrence_state"] == "CROSS_WINDOW_RECURRENT"
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_window_local_relationships_do_not_pass_stability():
    early, late = _rel(wallet="EARLY"), _rel(wallet="LATE")
    result = assess_developer_relationship_stability([
        _snap(1, 1, [early]), _snap(2, 5, [early]), _snap(3, 10, [late]), _snap(4, 15, [late])
    ])
    assert result["stable"] is False
    assert result["stability_status"] == "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["blockers"] == ["NO_CROSS_WINDOW_RECURRENCE"]
    assert result["window_local_only_count"] == 2


def test_small_history_is_not_evaluated():
    result = assess_developer_relationship_stability([_snap(1, 1, [_rel()]), _snap(2, 5, [_rel()])])
    assert result["stability_status"] == "NOT_EVALUATED"
    assert result["blockers"] == ["INSUFFICIENT_SNAPSHOT_HISTORY"]


def test_no_relationship_evidence_fails_closed():
    result = assess_developer_relationship_stability([
        _snap(1, 1, []), _snap(2, 5, []), _snap(3, 10, []), _snap(4, 15, [])
    ])
    assert result["blockers"] == ["NO_RELATIONSHIP_EVIDENCE"]
    assert result["stable"] is False


def test_as_of_excludes_future_and_invalid_evidence():
    rel = _rel()
    records = [_snap(1, 1, [rel]), _snap(2, 5, [rel]), _snap(3, 10, [rel]), _snap(4, 15, [rel])]
    records.append(_snap(5, 30, [_rel(wallet="FUTURE")]))
    records.append({"id": 6, "evidence_hash": "bad", "observed_at": None, "evidence": {}})
    result = assess_developer_relationship_stability(records, as_of="2026-08-20T00:00:00+00:00")
    assert result["stable"] is True
    assert result["snapshot_count"] == 4
    assert result["excluded_snapshot_count"] == 2
    assert result["temporal_cutoff_enforced"] is True


def test_duplicate_snapshot_hash_cannot_manufacture_history():
    rel = _rel()
    duplicate = _snap(1, 1, [rel])
    records = [duplicate, dict(duplicate), _snap(2, 5, [rel]), _snap(3, 10, [rel])]
    result = assess_developer_relationship_stability(records)
    assert result["stability_status"] == "NOT_EVALUATED"
    assert result["snapshot_count"] == 3


class _Mappings:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _Session:
    def __init__(self, rows): self.rows = rows; self.statement = None; self.params = None
    async def execute(self, statement, params):
        self.statement = str(statement); self.params = params
        return _Mappings(self.rows)


@pytest.mark.asyncio
async def test_db_entry_point_reads_immutable_history_with_temporal_cutoff():
    rel = _rel()
    rows = []
    for record in [_snap(1, 1, [rel]), _snap(2, 5, [rel]), _snap(3, 10, [rel]), _snap(4, 15, [rel])]:
        rows.append({**record,
                     "observed_at": datetime.fromisoformat(record["observed_at"]),
                     "ingested_at": datetime.fromisoformat(record["ingested_at"])})
    session = _Session(rows)
    cutoff = datetime(2026, 8, 20, tzinfo=timezone.utc)
    result = await developer_relationship_stability(session, "11111111-1111-1111-1111-111111111111", as_of=cutoff)
    assert result["stable"] is True
    assert result["status"] == "OBSERVED"
    assert "developer_correlation_snapshots" in session.statement
    assert "ingested_at <= :as_of" in session.statement
    assert session.params["as_of"] == cutoff
