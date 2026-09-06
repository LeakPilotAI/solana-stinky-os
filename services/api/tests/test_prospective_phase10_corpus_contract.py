from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]


def test_prospective_corpus_is_read_only_and_dual_time():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "insert into" not in lowered
    assert "update " not in lowered
    assert "delete from" not in lowered
    assert "l.event_id LIKE 'migrated:%'" in source
    assert 'r.get("observed_at") <= feature_as_of' in source
    assert 'r.get("ingested_at") <= feature_as_of' in source
    assert '"query_count_max": 4' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source


def test_collector_emits_sparse_durable_feature_snapshots():
    publisher = (ROOT / "services" / "post-migration-collector" / "src" / "post_migration" / "publisher.py").read_text(encoding="utf-8")
    tracker = (ROOT / "services" / "post-migration-collector" / "src" / "post_migration" / "tracker.py").read_text(encoding="utf-8")
    assert "force_durable=True" in publisher
    assert "phase10_feature_snapshot" in publisher
    assert "_PHASE10_FEATURE_HORIZONS" in tracker
    assert '("5m", 300)' in tracker
    assert "seconds_remaining <= lead_window" in tracker
    assert "_phase10_horizons_emitted" in tracker


def test_market_outcome_trigger_preserves_pre_and_post_horizon_evidence():
    migration = (ROOT / "services" / "entity-resolver" / "migrations" / "008_market_outcome_ingestion.sql").read_text(encoding="utf-8")
    lowered = migration.lower()
    assert "phase10_pre_cutoff_market_snapshot" in migration
    assert "seconds_before_cutoff <= 90" in migration
    assert "new.captured_at <=" not in lowered or "seconds_before_cutoff >= 0" in migration
    assert "market_snapshot_observation" in migration
    assert "select mt.migration_at" in lowered
    assert "ingested_at" in lowered
    assert "now()" in lowered


def test_no_historical_backfill_or_gate_change_in_activation_files():
    files = [
        ROOT / "services" / "entity-resolver" / "migrations" / "008_market_outcome_ingestion.sql",
        ROOT / "services" / "post-migration-collector" / "src" / "post_migration" / "publisher.py",
        ROOT / "services" / "post-migration-collector" / "src" / "post_migration" / "tracker.py",
        API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files).lower()
    assert "historical_feature_reconstruction_authorized" not in combined
    assert "min_feature_source_coverage" not in combined
    assert "min_label_coverage" not in combined
