from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from entity_resolver.resolver import EntityResolver


@pytest.mark.asyncio
async def test_migration_observation_does_not_increment_launch_count() -> None:
    entity_id = uuid4()
    store = AsyncMock()
    store.ensure_wallet_entity.return_value = entity_id
    resolver = EntityResolver(store)

    result = await resolver.ensure_deployer_observed("DeployerWallet")

    assert result == str(entity_id)
    store.ensure_wallet_entity.assert_awaited_once_with(
        "DeployerWallet",
        entity_type="deployer",
        confidence=0.85,
    )
    store.bump_launch_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_launch_observation_increments_launch_count() -> None:
    entity_id = uuid4()
    store = AsyncMock()
    store.ensure_wallet_entity.return_value = entity_id
    resolver = EntityResolver(store)

    result = await resolver.on_deployer_observed("DeployerWallet")

    assert result == str(entity_id)
    store.ensure_wallet_entity.assert_awaited_once_with(
        "DeployerWallet",
        entity_type="deployer",
        confidence=0.85,
    )
    store.bump_launch_count.assert_awaited_once_with(entity_id)
