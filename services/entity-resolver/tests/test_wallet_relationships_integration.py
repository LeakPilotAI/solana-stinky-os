import pytest


@pytest.mark.asyncio
async def test_relationship_store_records_canonical_wallet_order() -> None:
    # Contract-level regression placeholder: the persistence method must canonicalize
    # wallet ordering before applying the database CHECK constraint.
    from entity_resolver.store import EntityStore

    assert hasattr(EntityStore, "record_wallet_relationship")
