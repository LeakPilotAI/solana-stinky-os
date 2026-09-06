from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_history_requires_observed_and_ingested_cutoff():
    source = (ROOT / "src" / "stinky_api" / "market_outcome_history.py").read_text(encoding="utf-8")
    assert "observed_at <= :as_of AND ingested_at <= :as_of" in source


def test_motif_context_attaches_reference_launch_provenance_and_centralized_lifecycle_cutoff():
    context = (ROOT / "src" / "stinky_api" / "developer_motif_outcome_context.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "src" / "stinky_api" / "lifecycle_analogue_distribution.py").read_text(encoding="utf-8")
    assert "historical_launch_outcome_provenance" in context
    assert '"reference_launch_outcome_provenance"' in context
    assert "load_lifecycle_memories_for_mints" in context
    assert "o.observed_at <= :as_of AND o.ingested_at <= :as_of" in lifecycle
    assert "e.occurred_at <= :as_of AND e.ingested_at <= :as_of" in lifecycle


def test_provenance_reads_immutable_event_and_measured_observations():
    source = (ROOT / "src" / "stinky_api" / "historical_launch_outcome_provenance.py").read_text(encoding="utf-8")
    assert "post_migration.tracking_completed" in source
    assert "e.ingested_at <= :as_of" in source
    assert "o.ingested_at <= :as_of" in source
    assert "market_outcome_observations" in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
