from types import SimpleNamespace

import pytest

from stinky_api.entity_intelligence_calibration_readiness import _latest_component_evidence_hash
from stinky_api.entity_readiness_transition_audit import (
    describe_entity_readiness_transition,
    entity_readiness_hash,
)


def _readiness(developer_hash: str) -> dict:
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
