import pytest

import stinky_api.live_phase10_readiness as live


class _Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _dataset():
    return {
        "status": "OBSERVED",
        "formation_status": "READY_FOR_DESCRIPTIVE_DISCOVERY",
        "dataset_hash": "ds",
        "as_of": "2026-09-06T00:00:00+00:00",
        "feature_horizon": "5m",
        "row_count": 60,
        "coverage": {
            "label_coverage": 0.8,
            "developer_snapshot_coverage": 0.7,
            "correlation_snapshot_coverage": 0.7,
            "lifecycle_any_coverage": 0.7,
        },
        "criteria": {},
        "bounded": {"query_count": 3},
        "rows": [],
        "predictive_authority": False,
    }


def _discovery():
    return {
        "status": "OBSERVED",
        "discovery_status": "DESCRIPTIVE_PATTERNS_OBSERVED",
        "dataset_hash": "ds",
        "pattern_count": 3,
        "patterns": [
            {"pattern_hash": "p1", "pattern_key": "A", "feature_tokens": ["A"], "support_count": 10},
            {"pattern_hash": "p2", "pattern_key": "B", "feature_tokens": ["B"], "support_count": 9},
            {"pattern_hash": "p3", "pattern_key": "C", "feature_tokens": ["C"], "support_count": 8},
        ],
        "predictive_authority": False,
    }


def _validation():
    def p(i, state):
        return {
            "pattern_hash": f"p{i}",
            "pattern_key": chr(64 + i),
            "stability_status": state,
            "full_support_count": 10,
            "early": {"support_count": 5},
            "late": {"support_count": 5},
            "outcome_distribution_drift": {"max_drift_pct_points": 10.0},
            "dataset_hash": "ds",
        }
    return {
        "status": "OBSERVED",
        "validation_status": "TEMPORAL_VALIDATION_COMPLETE",
        "dataset_hash": "ds",
        "pattern_count": 3,
        "stability_counts": {"STABLE": 2, "UNSTABLE": 1, "INSUFFICIENT_EVIDENCE": 0},
        "patterns": [p(1, "STABLE"), p(2, "STABLE"), p(3, "UNSTABLE")],
        "predictive_authority": False,
    }


@pytest.mark.asyncio
async def test_live_chain_persists_current_validation_then_audits(monkeypatch):
    session = _Session()
    dataset = _dataset()
    discovery = _discovery()
    validation = _validation()
    persistence = {
        "status": "OBSERVED",
        "persisted_pattern_count": 3,
        "min_snapshot_depth": 2,
        "pattern_hashes": ["p1", "p2", "p3"],
        "snapshot_depths": {"p1": 2, "p2": 2, "p3": 2},
        "dual_temporal_cutoff_supported": True,
        "bounded": {"query_count": 1},
        "predictive_authority": False,
    }
    gate = {
        "completion_status": "PHASE_10_COMPLETE",
        "ready_for_phase_11_research": True,
        "failed_criteria": [],
        "predictive_authority": False,
    }

    async def fake_dataset(*args, **kwargs): return dataset
    def fake_discovery(*args, **kwargs): return discovery
    def fake_validation(*args, **kwargs): return validation
    async def fake_persist(session, pattern): return f"e-{pattern['pattern_hash']}"
    async def fake_summary(*args, **kwargs): return persistence
    def fake_gate(*args, **kwargs): return gate

    monkeypatch.setattr(live, "form_pattern_discovery_dataset", fake_dataset)
    monkeypatch.setattr(live, "discover_descriptive_patterns", fake_discovery)
    monkeypatch.setattr(live, "validate_pattern_temporal_stability", fake_validation)
    monkeypatch.setattr(live, "persist_pattern_stability_snapshot", fake_persist)
    monkeypatch.setattr(live, "pattern_persistence_readiness_summary", fake_summary)
    monkeypatch.setattr(live, "audit_phase10_readiness", fake_gate)

    result = await live.run_live_phase10_readiness(session)
    assert result["completion_status"] == "PHASE_10_COMPLETE"
    assert result["ready_for_phase_11_research"] is True
    assert result["persisted_or_deduped_evidence_count"] == 3
    assert result["persistence_write_status"] == "PERSISTED_OR_DEDUPED"
    assert result["command_center_coupled"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert session.commits == 1


@pytest.mark.asyncio
async def test_historical_replay_never_persists(monkeypatch):
    session = _Session()
    dataset = _dataset(); discovery = _discovery(); validation = _validation()

    async def fake_dataset(*args, **kwargs): return dataset
    def fake_discovery(*args, **kwargs): return discovery
    def fake_validation(*args, **kwargs): return validation
    async def should_not_persist(*args, **kwargs): raise AssertionError("historical replay must not persist")
    async def fake_summary(*args, **kwargs):
        assert kwargs.get("as_of") == "2026-09-01T00:00:00+00:00"
        return {"persisted_pattern_count": 0, "min_snapshot_depth": 0, "pattern_hashes": [], "dual_temporal_cutoff_supported": True, "predictive_authority": False}
    def fake_gate(*args, **kwargs):
        return {"completion_status": "NOT_READY_FOR_PHASE_11", "ready_for_phase_11_research": False, "failed_criteria": ["persistence_depth"], "predictive_authority": False}

    monkeypatch.setattr(live, "form_pattern_discovery_dataset", fake_dataset)
    monkeypatch.setattr(live, "discover_descriptive_patterns", fake_discovery)
    monkeypatch.setattr(live, "validate_pattern_temporal_stability", fake_validation)
    monkeypatch.setattr(live, "persist_pattern_stability_snapshot", should_not_persist)
    monkeypatch.setattr(live, "pattern_persistence_readiness_summary", fake_summary)
    monkeypatch.setattr(live, "audit_phase10_readiness", fake_gate)

    result = await live.run_live_phase10_readiness(session, as_of="2026-09-01T00:00:00+00:00")
    assert result["historical_replay"] is True
    assert result["persistence_write_status"] == "SKIPPED_HISTORICAL_REPLAY"
    assert session.commits == 0


@pytest.mark.asyncio
async def test_persistence_failure_fails_closed_without_crashing_audit(monkeypatch):
    session = _Session()
    dataset = _dataset(); discovery = _discovery(); validation = _validation()

    async def fake_dataset(*args, **kwargs): return dataset
    def fake_discovery(*args, **kwargs): return discovery
    def fake_validation(*args, **kwargs): return validation
    async def broken_persist(*args, **kwargs): raise RuntimeError("db down")
    async def fake_summary(*args, **kwargs):
        return {"persisted_pattern_count": 0, "min_snapshot_depth": 0, "pattern_hashes": [], "dual_temporal_cutoff_supported": True, "predictive_authority": False}
    def fake_gate(*args, **kwargs):
        return {"completion_status": "NOT_READY_FOR_PHASE_11", "ready_for_phase_11_research": False, "failed_criteria": ["persisted_pattern_count", "persistence_depth"], "predictive_authority": False}

    monkeypatch.setattr(live, "form_pattern_discovery_dataset", fake_dataset)
    monkeypatch.setattr(live, "discover_descriptive_patterns", fake_discovery)
    monkeypatch.setattr(live, "validate_pattern_temporal_stability", fake_validation)
    monkeypatch.setattr(live, "persist_pattern_stability_snapshot", broken_persist)
    monkeypatch.setattr(live, "pattern_persistence_readiness_summary", fake_summary)
    monkeypatch.setattr(live, "audit_phase10_readiness", fake_gate)

    result = await live.run_live_phase10_readiness(session)
    assert result["completion_status"] == "NOT_READY_FOR_PHASE_11"
    assert result["persistence_write_status"] == "UNAVAILABLE"
    assert session.rollbacks == 1
