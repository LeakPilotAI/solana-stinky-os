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


def test_legacy_relationship_kind_preserves_unknown_semantics() -> None:
    assert "legacy_unspecified" in MIGRATION
    update = MIGRATION.split("UPDATE wallet_relationships", 1)[1].split(
        "ALTER TABLE wallet_relationships", 1
    )[0]
    for inferred_kind in (
        "funding_observation",
        "deployer_buyer_association",
        "ownership",
        "coordination",
        "insider",
    ):
        assert inferred_kind not in update


def test_legacy_nullable_evidence_times_are_not_fabricated() -> None:
    assert "SET first_seen_at" not in MIGRATION
    assert "SET last_seen_at" not in MIGRATION
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


def test_relationship_migration_is_non_destructive() -> None:
    upper = MIGRATION.upper()
    assert "DROP TABLE" not in upper
    assert "TRUNCATE" not in upper
    assert "DELETE FROM WALLET_RELATIONSHIPS" not in upper
