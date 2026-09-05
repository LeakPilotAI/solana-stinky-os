import pytest


@pytest.mark.asyncio
async def test_relationship_store_exposes_persistent_contract() -> None:
    from entity_resolver.relationships import WalletRelationshipStore

    assert hasattr(WalletRelationshipStore, "record_relationship")
    assert hasattr(WalletRelationshipStore, "list_relationships")
