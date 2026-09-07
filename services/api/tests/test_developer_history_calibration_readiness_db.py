from datetime import datetime, timezone

import pytest

import stinky_api.developer_longitudinal_audit as audit
from stinky_api.developer_history_calibration_readiness import (
    developer_history_calibration_readiness,
)


class Session:
    pass


def _record(idx, observed_at, launches, evidence_hash):
    return {
        "id": idx,
        "evidence_hash": evidence_hash,
        "observed_at": observed_at,
        "ingested_at": observed_at,
        "evidence": {"launch_history": {"records": launches}},
    }


@pytest.mark.asyncio
async def test_db_entrypoint_uses_temporal_audit_history(monkeypatch):
    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)
    launches = [
        {"mint": "A", "observed_at": "2026-07-01T00:00:00+00:00", "outcome_status": "RUNNER"},
        {"mint": "B", "observed_at": "2026-07-05T00:00:00+00:00", "outcome_status": "FADE"},
        {"mint": "C", "observed_at": "2026-07-09T00:00:00+00:00", "outcome_status": "HELD"},
        {"mint": "D", "observed_at": "2026-07-13T00:00:00+00:00", "outcome_status": "RUNNER"},
        {"mint": "E", "observed_at": "2026-07-17T00:00:00+00:00", "outcome_status": "UNKNOWN"},
    ]
    seen = {}

    async def fake_history(session, entity_id, *, limit, as_of):
        seen.update({"session": session, "entity_id": entity_id, "limit": limit, "as_of": as_of})
        return {
            "status": "OBSERVED",
            "records": [
                _record(3, "2026-07-18T00:00:00+00:00", launches, "h3"),
                _record(2, "2026-07-14T00:00:00+00:00", launches[:4], "h2"),
                _record(1, "2026-07-10T00:00:00+00:00", launches[:3], "h1"),
            ],
        }

    monkeypatch.setattr(audit, "developer_audit_history", fake_history)
    session = Session()
    result = await developer_history_calibration_readiness(
        session,
        "11111111-1111-1111-1111-111111111111",
        limit=500,
        as_of=cutoff,
    )

    assert seen["session"] is session
    assert seen["limit"] == 100
    assert seen["as_of"] == cutoff
    assert result["status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["ready"] is True
    assert result["source"] == "developer_longitudinal_snapshots"
    assert result["source_status"] == "OBSERVED"
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_db_entrypoint_fails_closed_when_audit_history_unavailable(monkeypatch):
    async def fake_history(session, entity_id, *, limit, as_of):
        return {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["developer_longitudinal_snapshots"],
        }

    monkeypatch.setattr(audit, "developer_audit_history", fake_history)
    result = await developer_history_calibration_readiness(
        Session(),
        "11111111-1111-1111-1111-111111111111",
    )

    assert result["status"] == "UNKNOWN"
    assert result["ready"] is False
    assert result["blockers"][0] == "AUDIT_HISTORY_UNAVAILABLE"
    assert result["missing"] == ["developer_longitudinal_snapshots"]
    assert result["predictive_authority"] is False
    assert result["quality_inferred"] is False
