from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stinky_api.entity_intelligence_calibration_readiness import (
    _latest_component_evidence_hash,
    _latest_launch_boundary_hash,
)
from stinky_api.entity_readiness_transition_audit import (
    describe_entity_readiness_transition,
    entity_readiness_hash,
)


def _readiness(developer_hash: str, outcome_hash: str | None = None) -> dict:
    return {
        "status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": False,
        "blockers": [
            "DEVELOPER_HISTORY_NOT_STABLE",
            "RELATIONSHIP_HISTORY_NOT_STABLE",
            "OUTCOME_HISTORY_UNAVAILABLE",
        ],
        "components": {
            "developer_history": {
                "status": "NOT_EVALUATED",
                "passed": False,
                "blockers": ["READINESS_GATE_NOT_PASSED"],
                "evidence_hash": developer_hash,
            },
            "relationship_history": {
                "status": "NOT_EVALUATED",
                "passed": False,
                "blockers": ["READINESS_GATE_NOT_PASSED"],
                "evidence_hash": "relationship-v1",
            },
            "outcome_history": {
                "status": "UNKNOWN",
                "passed": False,
                "launch_count_observed": 0,
                "outcomes_known": 0,
                "outcome_coverage": None,
                "evidence_hash": outcome_hash,
            },
        },
        "temporal_integrity": {
            "developer_cutoff_enforced": None,
            "relationship_cutoff_enforced": None,
        },
        "evidence_independence": {
            "developer_source": "developer_longitudinal_snapshots",
            "relationship_source": "developer_correlation_snapshots",
            "outcome_source": "entity_launches",
            "distinct_sources": True,
        },
        "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
    }


def test_component_evidence_hash_creates_real_readiness_evidence_transition():
    previous = _readiness("developer-v1")
    current = _readiness("developer-v2")

    assert entity_readiness_hash(previous) != entity_readiness_hash(current)
    transition = describe_entity_readiness_transition(previous, current)
    assert transition["transition"] == "READINESS_EVIDENCE_CHANGED"
    assert transition["changed"] is True
    assert any(
        change.get("kind") == "COMPONENT_CHANGED"
        and change.get("component") == "developer_history"
        for change in transition["changes"]
    )


def test_current_launch_boundary_creates_repeat_checkpoint_without_changing_gate():
    previous = _readiness("developer-v1", "launch-before-outcome")
    current = _readiness("developer-v1", "launch-after-outcome")

    assert previous["status"] == current["status"]
    assert previous["blockers"] == current["blockers"]
    assert entity_readiness_hash(previous) != entity_readiness_hash(current)
    transition = describe_entity_readiness_transition(previous, current)
    assert transition["transition"] == "READINESS_EVIDENCE_CHANGED"
    assert any(
        change.get("kind") == "COMPONENT_CHANGED"
        and change.get("component") == "outcome_history"
        for change in transition["changes"]
    )


class _Result:
    def __init__(self, value):
        self._value = value

    def first(self):
        return (self._value,) if self._value is not None else None


class _Session:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.value)


class _MappingResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _MappingSession:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _MappingResult(self.row)


@pytest.mark.asyncio
async def test_latest_component_evidence_hash_reads_immutable_snapshot_version():
    session = _Session("developer-v2")
    digest = await _latest_component_evidence_hash(
        session,
        table="developer_longitudinal_snapshots",
        entity_id="00000000-0000-0000-0000-000000000321",
        as_of=None,
    )

    assert digest == "developer-v2"
    assert "developer_longitudinal_snapshots" in session.calls[0][0]
    assert session.calls[0][1]["entity_id"] == "00000000-0000-0000-0000-000000000321"


@pytest.mark.asyncio
async def test_latest_component_evidence_hash_rejects_unapproved_table_name():
    session = _Session("should-not-be-read")
    digest = await _latest_component_evidence_hash(
        session,
        table="entity_launches; DROP TABLE entities",
        entity_id="00000000-0000-0000-0000-000000000321",
        as_of=None,
    )

    assert digest is None
    assert session.calls == []


@pytest.mark.asyncio
async def test_latest_launch_boundary_hash_changes_after_measured_completion():
    entity_id = "00000000-0000-0000-0000-000000000321"
    observed_at = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    before = _MappingSession(
        {
            "mint": "MintOutcome",
            "observed_at": observed_at,
            "outcome_status": None,
            "outcome_meta": None,
        }
    )
    after = _MappingSession(
        {
            "mint": "MintOutcome",
            "observed_at": observed_at,
            "outcome_status": "completed",
            "outcome_meta": {"observed_at": "2026-09-07T12:30:00+00:00", "trades_seen": 12},
        }
    )

    before_hash = await _latest_launch_boundary_hash(before, entity_id=entity_id, as_of=None)
    after_hash = await _latest_launch_boundary_hash(after, entity_id=entity_id, as_of=None)

    assert before_hash is not None
    assert after_hash is not None
    assert before_hash != after_hash
    assert "entity_launches" in before.calls[0][0]


@pytest.mark.asyncio
async def test_latest_launch_boundary_hash_does_not_reconstruct_historical_outcome_state():
    session = _MappingSession(
        {
            "mint": "MintOutcome",
            "observed_at": datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
            "outcome_status": "completed",
            "outcome_meta": {"observed_at": "2026-09-07T12:30:00+00:00"},
        }
    )

    digest = await _latest_launch_boundary_hash(
        session,
        entity_id="00000000-0000-0000-0000-000000000321",
        as_of=datetime(2026, 9, 7, 12, 15, tzinfo=timezone.utc),
    )

    assert digest is None
    assert session.calls == []
