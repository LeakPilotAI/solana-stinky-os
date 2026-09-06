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


def test_legacy_relationship_kind_preserves_unknown_semantics() -> None:
    assert "legacy_unspecified" in MIGRATION
    for inferred_kind in (
        "funding_observation",
        "deployer_buyer_association",
        "ownership",
        "coordination",
        "insider",
    ):
        update = MIGRATION.split("UPDATE wallet_relationships", 1)[1].split(
            "ALTER TABLE wallet_relationships", 1
        )[0]
        assert inferred_kind not in update


def test_relationship_migration_supplies_conflict_arbiter_for_legacy_table() -> None:
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique" in MIGRATION
    assert "ON wallet_relationships (wallet_a, wallet_b, relationship_kind)" in MIGRATION


def test_relationship_migration_is_non_destructive() -> None:
    upper = MIGRATION.upper()
    assert "DROP TABLE" not in upper
    assert "TRUNCATE" not in upper
    assert "DELETE FROM WALLET_RELATIONSHIPS" not in upper
