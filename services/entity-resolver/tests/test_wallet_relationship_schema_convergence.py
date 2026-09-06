from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "005_wallet_relationships.sql"
).read_text(encoding="utf-8")


def test_relationship_migration_converges_legacy_missing_kind() -> None:
    assert "ADD COLUMN IF NOT EXISTS relationship_kind TEXT" in MIGRATION
    assert "SET relationship_kind = 'legacy_unspecified'" in MIGRATION
    assert "WHERE relationship_kind IS NULL" in MIGRATION
    assert "ALTER COLUMN relationship_kind SET NOT NULL" in MIGRATION


def test_relationship_migration_converges_all_current_store_columns() -> None:
    expected = (
        "relationship_kind TEXT",
        "observation_count INT",
        "first_seen_at TIMESTAMPTZ",
        "last_seen_at TIMESTAMPTZ",
        "confidence DOUBLE PRECISION",
        "evidence JSONB",
        "created_at TIMESTAMPTZ",
        "updated_at TIMESTAMPTZ",
    )
    for column in expected:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in MIGRATION


def test_legacy_adr012_kind_is_bridged_as_factual_provenance() -> None:
    assert "column_name = 'kind'" in MIGRATION
    assert "SET relationship_kind = kind" in MIGRATION
    assert "AND kind IS NOT NULL" in MIGRATION
    assert "ALTER COLUMN kind DROP NOT NULL" in MIGRATION


def test_legacy_adr012_observed_at_is_bridged_without_fabrication() -> None:
    assert "column_name = 'observed_at'" in MIGRATION
    assert "SET first_seen_at = observed_at" in MIGRATION
    assert "SET last_seen_at = observed_at" in MIGRATION
    assert "AND observed_at IS NOT NULL" in MIGRATION
    assert "ALTER COLUMN observed_at DROP NOT NULL" in MIGRATION


def test_legacy_adr012_required_columns_no_longer_block_modern_writes() -> None:
    for column in ("kind", "mint", "observed_at", "reason"):
        assert f"ALTER COLUMN {column} DROP NOT NULL" in MIGRATION


def test_optional_legacy_columns_are_guarded_for_fresh_schema() -> None:
    assert "DO $bridge$" in MIGRATION
    for column in ("kind", "mint", "observed_at", "reason"):
        assert f"column_name = '{column}'" in MIGRATION
    assert "information_schema.columns" in MIGRATION


def test_legacy_relationship_kind_preserves_unknown_semantics_when_unrecoverable() -> None:
    assert "legacy_unspecified" in MIGRATION
    for inferred_kind in (
        "funding_observation",
        "deployer_buyer_association",
        "ownership",
        "coordination",
        "insider",
    ):
        assert f"SET relationship_kind = '{inferred_kind}'" not in MIGRATION


def test_legacy_nullable_evidence_times_are_not_fabricated() -> None:
    assert "SET first_seen_at = now()" not in MIGRATION
    assert "SET last_seen_at = now()" not in MIGRATION
    assert "SET created_at =" not in MIGRATION
    assert "SET updated_at =" not in MIGRATION
    assert "ALTER COLUMN created_at SET DEFAULT now()" in MIGRATION
    assert "ALTER COLUMN updated_at SET DEFAULT now()" in MIGRATION
    assert "ALTER COLUMN created_at SET NOT NULL" not in MIGRATION
    assert "ALTER COLUMN updated_at SET NOT NULL" not in MIGRATION


def test_storage_baselines_are_explicit_and_non_inferential() -> None:
    assert "SET observation_count = 1" in MIGRATION
    assert "WHERE observation_count IS NULL" in MIGRATION
    assert "SET evidence = '{}'::jsonb" in MIGRATION
    assert "WHERE evidence IS NULL" in MIGRATION
    assert "ALTER COLUMN observation_count SET DEFAULT 1" in MIGRATION
    assert "ALTER COLUMN observation_count SET NOT NULL" in MIGRATION
    assert "ALTER COLUMN evidence SET DEFAULT '{}'::jsonb" in MIGRATION
    assert "ALTER COLUMN evidence SET NOT NULL" in MIGRATION


def test_relationship_migration_supplies_conflict_arbiter_for_legacy_table() -> None:
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique" in MIGRATION
    assert "ON wallet_relationships (wallet_a, wallet_b, relationship_kind)" in MIGRATION


def test_relationship_migration_preserves_legacy_columns_and_rows() -> None:
    upper = MIGRATION.upper()
    assert "DROP TABLE" not in upper
    assert "TRUNCATE" not in upper
    assert "DELETE FROM WALLET_RELATIONSHIPS" not in upper
    for column in ("KIND", "MINT", "OBSERVED_AT", "REASON"):
        assert f"DROP COLUMN {column}" not in upper
