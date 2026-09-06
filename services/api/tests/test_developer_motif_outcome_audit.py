from datetime import datetime, timezone

from stinky_api.developer_motif_outcome_audit import (
    describe_motif_outcome_change,
    motif_outcome_context_hash,
)


def _context(outcome="UNKNOWN", *, analogue=True, missing=None):
    records = []
    if analogue:
        records = [{
            "motif_kind": "CROSS_ENTITY_RELATIONSHIP_MOTIF",
            "motif_state": "MULTI_COMPONENT_CONSTELLATION",
            "component_kinds": ["SHARED_FUNDER", "WALLET_REUSE"],
            "related_entity_ids": ["22222222-2222-2222-2222-222222222222"],
            "launches": [{
                "entity_id": "22222222-2222-2222-2222-222222222222",
                "mint": "M1",
                "launch_observed_at": "2026-09-01T00:00:00+00:00",
                "outcome": outcome,
                "outcome_observed_at": None if outcome == "UNKNOWN" else "2026-09-05T00:00:00+00:00",
            }],
        }]
    counts = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    if analogue:
        counts[outcome] = 1
    return {
        "status": "OBSERVED" if analogue else "NEW-UNKNOWN",
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "motif_analogue_count": 1 if analogue else 0,
        "launch_analogue_count": 1 if analogue else 0,
        "outcome_counts": counts,
        "records": records,
        "missing": missing or [],
        "analogue_history_is_not_prediction": True,
        "predictive_authority": False,
        "trade_signal": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "evidence_only": True,
    }


def test_hash_changes_when_historical_outcome_resolves():
    before = _context("UNKNOWN")
    after = _context("RUNNER")
    assert motif_outcome_context_hash(before) != motif_outcome_context_hash(after)


def test_unknown_to_runner_is_factual_resolution_event():
    change = describe_motif_outcome_change(_context("UNKNOWN"), _context("RUNNER"))
    kinds = [row["kind"] for row in change["changes"]]
    assert "HISTORICAL_OUTCOME_RESOLVED" in kinds
    assert "HISTORICAL_OUTCOME_COUNTS_CHANGED" in kinds
    assert change["predictive_authority"] is False
    assert change["trade_signal"] is False
    assert change["risk_inferred"] is False
    assert change["quality_inferred"] is False


def test_new_analogue_and_launch_are_factual_additions():
    change = describe_motif_outcome_change(_context(analogue=False), _context("UNKNOWN"))
    kinds = [row["kind"] for row in change["changes"]]
    assert "MOTIF_ANALOGUE_ADDED" in kinds
    assert "HISTORICAL_LAUNCH_ADDED" in kinds


def test_removed_evidence_is_not_interpreted_as_improvement():
    change = describe_motif_outcome_change(_context("FADE"), _context(analogue=False))
    kinds = [row["kind"] for row in change["changes"]]
    assert "MOTIF_ANALOGUE_REMOVED_OR_UNAVAILABLE" in kinds
    assert "HISTORICAL_LAUNCH_REMOVED_OR_UNAVAILABLE" in kinds
    serialized = str(change).lower()
    for forbidden in ("bullish", "bearish", "safe", "suspicious", "risk_score", "quality_score", "probability"):
        assert forbidden not in serialized


def test_identical_context_is_dedup_stable():
    a = _context("HELD")
    b = _context("HELD")
    assert motif_outcome_context_hash(a) == motif_outcome_context_hash(b)
    change = describe_motif_outcome_change(a, b)
    assert change["status"] == "UNCHANGED"
    assert change["changes"] == []


def test_audit_query_requires_observed_and_ingested_cutoffs():
    from pathlib import Path
    text = Path("services/api/src/stinky_api/developer_motif_outcome_audit.py").read_text()
    assert "observed_at <= :as_of AND ingested_at <= :as_of" in text
    assert "UNIQUE (entity_id, evidence_hash)" in text
