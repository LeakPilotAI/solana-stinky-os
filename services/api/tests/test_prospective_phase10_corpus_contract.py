from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]


def test_prospective_corpus_is_read_only_and_dual_time():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "insert into" not in lowered
    assert "update " not in lowered
    assert "delete from" not in lowered
    assert "e.event_type = 'token.migrated'" in source
    assert "DISTINCT ON (e.payload->>'mint')" in source
    assert "e.ingested_at <= e.occurred_at + make_interval" in source
    assert "l.event_id LIKE 'migrated:%'" not in source
    assert 'r.get("observed_at") <= feature_as_of' in source
    assert 'r.get("ingested_at") <= feature_as_of' in source
    assert '"query_count_max": 5' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source


def test_migration_cohort_deduplicates_and_joins_existing_launch_identity():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert "canonical_migrations" in source
    assert "ORDER BY e.payload->>'mint', e.occurred_at ASC, e.ingested_at ASC" in source
    assert "LEFT JOIN LATERAL" in source
    assert "WHERE el.mint = m.mint" in source
    assert "el.observed_at <= :dataset_as_of" in source
    assert "el.created_at <= :dataset_as_of" in source
    assert "l.deployer_wallet = m.creator" not in source
    assert "ORDER BY el.observed_at ASC, el.created_at ASC, el.id ASC" in source
    assert '"entity_launch_event_id_required": False' in source
    assert '"canonical_launch_identity": "earliest dual-time-visible entity_launches row by mint"' in source
    assert '"migration_creator_may_disagree_with_launch_identity": True' in source
    assert '"migration_events_deduplicated_by": "mint"' in source
    assert '"migration_anchor": "earliest dual-time-visible token.migrated event per mint"' in source


def test_feature_horizon_is_anchored_to_migration_not_original_launch():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert "m.migration_observed_at + make_interval(secs => :feature_seconds) AS feature_as_of" in source
    assert '"migration_observed_at"' in source
    assert '"migration_ingested_at"' in source
    assert '"launch_event_id"' in source


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


def test_feature_complete_requires_matching_phase10_pre_cutoff_snapshot():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert '300: "5m"' in source
    assert '900: "15m"' in source
    assert '1800: "30m"' in source
    assert 'r.get("evidence_basis") == "phase10_pre_cutoff_market_snapshot"' in source
    assert 'r.get("horizon") == feature_horizon_name' in source
    assert '"feature_evidence_basis_required": "phase10_pre_cutoff_market_snapshot"' in source


def test_prospective_labels_require_dual_time_immutable_ledger():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert "to_regclass('entity_launch_outcome_labels')" in source
    assert "FROM entity_launch_outcome_labels" in source
    assert "observed_at <= :dataset_as_of" in source
    assert "ingested_at <= :dataset_as_of" in source
    assert 'outcome_label = str(label_row.get("label"))' in source
    assert 'else "UNKNOWN"' in source
    assert '"outcome_label_source": "entity_launch_outcome_labels"' in source
    assert '"missing_or_late_outcome_label": "UNKNOWN"' in source


def test_prospective_corpus_pins_one_outcome_label_version():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert 'CANONICAL_OUTCOME_LABEL_VERSION = "outcome-v1.1.0"' in source
    assert "outcome_label_version: str = CANONICAL_OUTCOME_LABEL_VERSION" in source
    assert "AND label_version = :outcome_label_version" in source
    assert '"outcome_label_version_required": requested_label_version' in source


def test_calibration_usable_requires_complete_features_and_label():
    source = (API_ROOT / "src" / "stinky_api" / "prospective_phase10_corpus.py").read_text(encoding="utf-8")
    assert "calibration_usable = complete and label_complete" in source
    assert '"calibration_usable": calibration_usable' in source
    assert '"outcome_label_complete_count": label_complete_count' in source
    assert '"outcome_label_complete_coverage": label_complete_count / total' in source
    assert '"calibration_usable_count": calibration_usable_count' in source
    assert '"calibration_usable_coverage": calibration_usable_count / total' in source
    assert '"calibration_usable_requires": ["feature_complete", "outcome_label_complete"]' in source
