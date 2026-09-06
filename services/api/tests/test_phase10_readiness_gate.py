from datetime import datetime, timezone

import pytest

from stinky_api.phase10_readiness_gate import (
    audit_phase10_readiness,
    pattern_persistence_readiness_summary,
)


def _row(i, outcome="FADE"):
    return {
        "mint": f"M{i}",
        "row_hash": f"row-{i}",
        "label": {"outcome": outcome},
    }


def _inputs():
    rows = [_row(i, "UNKNOWN" if i == 0 else "FADE") for i in range(60)]
    dataset = {
        "formation_status": "READY_FOR_DESCRIPTIVE_DISCOVERY",
        "dataset_hash": "ds1",
        "row_count": len(rows),
        "rows": rows,
        "coverage": {
            "label_coverage": 59 / 60,
            "developer_snapshot_coverage": 0.9,
            "correlation_snapshot_coverage": 0.8,
            "lifecycle_any_coverage": 0.85,
        },
        "predictive_authority": False,
    }
    patterns = [
        {"pattern_hash": "p1", "pattern_key": "a", "feature_tokens": ["a"]},
        {"pattern_hash": "p2", "pattern_key": "b", "feature_tokens": ["b"]},
        {"pattern_hash": "p3", "pattern_key": "c", "feature_tokens": ["c"]},
    ]
    discovery = {
        "discovery_status": "DESCRIPTIVE_PATTERNS_OBSERVED",
        "dataset_hash": "ds1",
        "patterns": patterns,
        "predictive_authority": False,
    }
    validation = {
        "validation_status": "TEMPORAL_VALIDATION_COMPLETE",
        "dataset_hash": "ds1",
        "patterns": [
            {"pattern_hash": "p1", "stability_status": "STABLE"},
            {"pattern_hash": "p2", "stability_status": "UNSTABLE"},
            {"pattern_hash": "p3", "stability_status": "INSUFFICIENT_EVIDENCE"},
        ],
        "predictive_authority": False,
    }
    persistence = {
        "persisted_pattern_count": 2,
        "min_snapshot_depth": 2,
        "pattern_hashes": ["p1", "p2"],
        "dual_temporal_cutoff_supported": True,
        "predictive_authority": False,
    }
    return dataset, discovery, validation, persistence


def test_phase10_gate_passes_only_when_all_named_evidence_criteria_pass():
    result = audit_phase10_readiness(*_inputs())
    assert result["completion_status"] == "PHASE_10_COMPLETE"
    assert result["ready_for_phase_11_research"] is True
    assert result["failed_check_count"] == 0
    assert result["passed_check_count"] == result["check_count"]
    assert result["unknown_label_count"] == 1
    assert result["phase_11_authorized"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_phase10_gate_fails_closed_and_names_failed_criteria():
    dataset, discovery, validation, persistence = _inputs()
    dataset["coverage"]["label_coverage"] = 0.2
    discovery["patterns"] = discovery["patterns"][:1]
    validation["patterns"] = [{"pattern_hash": "p1", "stability_status": "INSUFFICIENT_EVIDENCE"}]
    persistence["persisted_pattern_count"] = 1
    persistence["min_snapshot_depth"] = 1
    persistence["pattern_hashes"] = ["p1"]
    result = audit_phase10_readiness(dataset, discovery, validation, persistence)
    assert result["completion_status"] == "NOT_READY_FOR_PHASE_11"
    assert result["ready_for_phase_11_research"] is False
    assert "label_coverage" in result["failed_criteria"]
    assert "pattern_count" in result["failed_criteria"]
    assert "temporally_sufficient_pattern_count" in result["failed_criteria"]
    assert "persistence_depth" in result["failed_criteria"]


def test_gate_rejects_cross_layer_identity_mismatch():
    dataset, discovery, validation, persistence = _inputs()
    discovery["dataset_hash"] = "wrong"
    validation["patterns"][0]["pattern_hash"] = "invented"
    persistence["pattern_hashes"] = ["p1", "not-validated"]
    result = audit_phase10_readiness(dataset, discovery, validation, persistence)
    assert result["completion_status"] == "NOT_READY_FOR_PHASE_11"
    assert "discovery_dataset_identity" in result["failed_criteria"]
    assert "validation_pattern_identity" in result["failed_criteria"]
    assert "persistence_pattern_identity" in result["failed_criteria"]


def test_duplicate_or_missing_row_and_pattern_hashes_fail_integrity():
    dataset, discovery, validation, persistence = _inputs()
    dataset["rows"][1]["row_hash"] = dataset["rows"][0]["row_hash"]
    discovery["patterns"][1]["pattern_hash"] = discovery["patterns"][0]["pattern_hash"]
    result = audit_phase10_readiness(dataset, discovery, validation, persistence)
    assert "row_hash_integrity" in result["failed_criteria"]
    assert "pattern_hash_integrity" in result["failed_criteria"]


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self, rows): self.rows = rows; self.calls = []
    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_persistence_summary_uses_one_bulk_query_and_dual_as_of_cutoff():
    session = _Session([
        {"pattern_hash": "p1", "snapshot_count": 3},
        {"pattern_hash": "p2", "snapshot_count": 2},
    ])
    cutoff = datetime(2026, 9, 6, tzinfo=timezone.utc)
    result = await pattern_persistence_readiness_summary(session, ["p2", "p1", "p1"], as_of=cutoff)
    assert result["persisted_pattern_count"] == 2
    assert result["min_snapshot_depth"] == 2
    assert result["bounded"]["query_count"] == 1
    assert result["temporal_cutoff_enforced"] is True
    sql = session.calls[0][0]
    assert "observed_at <= :as_of" in sql
    assert "ingested_at <= :as_of" in sql
    assert session.calls[0][1]["pattern_hashes"] == ["p1", "p2"]
