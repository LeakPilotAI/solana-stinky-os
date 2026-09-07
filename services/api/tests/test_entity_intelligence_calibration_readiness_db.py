import pytest

import stinky_api.developer_history_calibration_stability as developer_mod
import stinky_api.developer_relationship_stability as relationship_mod
from stinky_api.entity_intelligence_calibration_readiness import entity_intelligence_calibration_readiness


@pytest.mark.asyncio
async def test_db_backed_combined_gate_composes_existing_history_contracts(monkeypatch):
    async def fake_developer(session, entity_id, *, limit=100, as_of=None):
        return {
            "entity_id": entity_id,
            "stable": True,
            "stability_status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION",
            "blockers": [],
            "source": "developer_longitudinal_snapshots",
            "temporal_cutoff_enforced": True,
        }

    async def fake_relationship(session, entity_id, *, limit=40, as_of=None):
        return {
            "entity_id": entity_id,
            "stable": True,
            "stability_status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION",
            "blockers": [],
            "source": "developer_correlation_snapshots",
            "temporal_cutoff_enforced": True,
        }

    monkeypatch.setattr(developer_mod, "developer_history_calibration_stability", fake_developer)
    monkeypatch.setattr(relationship_mod, "developer_relationship_stability", fake_relationship)

    outcome = {
        "status": "OBSERVED",
        "launch_count_observed": 6,
        "outcomes_known": 5,
        "outcomes_unknown": 1,
        "outcome_coverage": 5 / 6,
        "evidence_basis": "entity_launches",
    }
    result = await entity_intelligence_calibration_readiness(
        object(), "11111111-1111-1111-1111-111111111111", outcome,
        as_of=None,
    )
    assert result["entity_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["ready"] is True
    assert result["status"] == "READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
