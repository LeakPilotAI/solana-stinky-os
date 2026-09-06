from __future__ import annotations

from pathlib import Path

import stinky_api.historical_evidence_reconstruction as module


def test_historical_reconstruction_requires_dual_event_cutoff_and_never_backdates_snapshots():
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "e.occurred_at <= m.feature_as_of" in source
    assert "e.ingested_at <= m.feature_as_of" in source
    assert '"derived_snapshots_are_not_backdated": True' in source
    assert '"historical_developer_snapshot_reconstruction_authorized": False' in source
    assert '"historical_correlation_snapshot_reconstruction_authorized": False' in source
    assert "historical_snapshots_backdated" in source
    assert '"historical_snapshots_backdated": False' in source


def test_launch_recovery_preserves_observation_time_but_uses_real_insert_time():
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "migration_at" in source
    assert "INSERT INTO entity_launches" in source
    assert "observed_at" in source
    # created_at is deliberately omitted from the INSERT so PostgreSQL NOW() remains ingestion time.
    launch_insert = source.split("INSERT INTO entity_launches", 1)[1].split("ON CONFLICT", 1)[0]
    assert "created_at" not in launch_insert
    assert "entity_launch_count_aggregate_modified" in source
    assert '"entity_launch_count_aggregate_modified": False' in source


def test_recovery_uses_direct_migration_creator_identity_not_future_graph_inference():
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "migration_tracks.creator" in source
    assert "migration_creator_observed" in source
    assert '"ownership_inferred": False' in source
    assert '"identity_inferred": False' in source
    assert '"future_entity_graph_inference_forbidden_for_historical_features": True' in source
