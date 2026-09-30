from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "genesis_postgres_backup.py"


def _module():
    spec = importlib.util.spec_from_file_location("genesis_postgres_backup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_backup_contract_covers_replay_critical_evidence_tables():
    module = _module()
    required = set(module.REQUIRED_TABLES)
    for name in (
        "events", "market_snapshots", "market_inspections", "entity_launches",
        "entity_launch_outcome_labels", "developer_longitudinal_snapshots",
        "developer_correlation_snapshots", "market_outcome_observations",
        "market_path_patterns", "market_path_pattern_occurrences",
        "paper_intake_producer_state", "paper_prospective_candidate",
        "paper_policy_registry", "paper_policy_active",
        "paper_policy_activation_audit", "paper_runtime_intake",
        "paper_runtime_record",
    ):
        assert name in required


def test_backup_contract_is_isolated_and_fail_closed():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "restored_over_source" in source
    assert '"restored_over_source": False' in source
    assert "genesis_restore_" in source
    assert "missing_required_tables:" in source
    assert "restored_manifest_mismatch" in source
    assert "source_integrity_failed:" in source
    assert "timescaledb_pre_restore()" in source
    assert "timescaledb_post_restore()" in source
    assert "pg.drop_database(restore_db)" in source
    assert "content_sha256(row.get(\"t0_evidence\"))" in source
    assert "content_sha256(row.get(\"payload\"))" in source
    assert "validated_policy_identity(identity)" in source


def test_backup_launcher_uses_canonical_container_and_database():
    source = (ROOT / "Backup-Genesis.cmd").read_text(encoding="utf-8")
    assert "genesis_postgres_backup.py" in source
    assert "--database stinky" in source
    assert "--mode docker-network" in source
    assert "--network project-genesis_default" in source
    assert "--db-host postgres" in source
    assert "--port 5432" in source


def test_large_table_manifest_streams_instead_of_buffering_every_row():
    source = SCRIPT.read_text(encoding="utf-8")
    build_manifest = source.split("def build_manifest", 1)[1].split("def _write_json", 1)[0]
    assert "_table_digest(pg, database, table)" in build_manifest
    assert "rows = _json_rows(pg, database, table)" not in build_manifest
    assert "def stream_digest" in source
    assert "STREAM_PROGRESS_ROWS = 100_000" in source
    assert "[manifest]" in source
    assert "BACKUP_COMMAND_TIMEOUT_SECONDS" in source
    assert "ordered_row_sha256_v1" in source


def test_local_backup_uses_compose_network_sidecars_not_exec_or_host_ports():
    source = SCRIPT.read_text(encoding="utf-8")
    launcher = (ROOT / "Backup-Genesis.cmd").read_text(encoding="utf-8")
    assert '"docker", "exec"' not in source
    assert "host.docker.internal" not in source
    assert "--host 127.0.0.1" not in launcher
    assert "--port 5433" not in launcher
    assert '"--network", self.network' in source
    assert '"-h", self.db_host' in source
    assert "sha256sum" in source
