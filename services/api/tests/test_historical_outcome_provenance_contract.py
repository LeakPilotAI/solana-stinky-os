from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_history_requires_observed_and_ingested_cutoff():
    source = (ROOT / "src" / "stinky_api" / "market_outcome_history.py").read_text(encoding="utf-8")
    assert "observed_at <= :as_of AND ingested_at <= :as_of" in source


def test_motif_context_attaches_reference_launch_provenance():
    source = (ROOT / "src" / "stinky_api" / "developer_motif_outcome_context.py").read_text(encoding="utf-8")
    assert "historical_launch_outcome_provenance" in source
    assert '"reference_launch_outcome_provenance"' in source
    assert "ingested_dt is None or ingested_dt > cutoff" in source


def test_provenance_reads_immutable_event_and_measured_observations():
    source = (ROOT / "src" / "stinky_api" / "historical_launch_outcome_provenance.py").read_text(encoding="utf-8")
    assert "post_migration.tracking_completed" in source
    assert "e.ingested_at <= :as_of" in source
    assert "o.ingested_at <= :as_of" in source
    assert "market_outcome_observations" in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
