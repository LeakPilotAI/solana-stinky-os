from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_post_migration_collector_does_not_emit_market_snapshot_events_today():
    publisher = (
        ROOT
        / "post-migration-collector"
        / "src"
        / "post_migration"
        / "publisher.py"
    ).read_text(encoding="utf-8")
    assert "EventType.POST_MIGRATION_MARKET_SNAPSHOT" in publisher
    assert "_SKIP_STREAM" in publisher
    assert "_SKIP_HTTP = _SKIP_STREAM" in publisher


def test_market_snapshot_schema_has_capture_time_but_no_independent_ingestion_time():
    migration = (
        ROOT
        / "post-migration-collector"
        / "migrations"
        / "001_post_migration_schema.sql"
    ).read_text(encoding="utf-8")
    start = migration.index("CREATE TABLE IF NOT EXISTS market_snapshots")
    end = migration.index("CREATE INDEX IF NOT EXISTS idx_market_snapshots_mint_time", start)
    block = migration[start:end]
    assert "captured_at" in block
    assert "ingested_at" not in block
    assert "created_at" not in block
