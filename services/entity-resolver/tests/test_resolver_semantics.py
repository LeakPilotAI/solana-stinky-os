from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from entity_resolver.resolver import EntityResolver
from entity_resolver.service import EntityService


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


def test_event_timestamp_preserves_timezone_and_precision() -> None:
    observed = "2026-09-04T12:34:56.123456+00:00"
    result = EntityService._event_timestamp({"observed_at": observed, "payload": {}})

    assert result == datetime(2026, 9, 4, 12, 34, 56, 123456, tzinfo=timezone.utc)


def test_event_timestamp_defaults_to_utc_when_missing() -> None:
    result = EntityService._event_timestamp({"payload": {}})

    assert result.tzinfo == timezone.utc


def test_outcome_payload_requires_measured_status() -> None:
    assert EntityService._outcome_payload({"payload": {"mint": "MINT"}}) == (
        "MINT",
        None,
        {},
    )


def test_outcome_payload_preserves_completion_evidence() -> None:
    result = EntityService._outcome_payload(
        {
            "payload": {
                "mint": "MINT",
                "outcome_status": "completed",
                "peak_multiple": 3.2,
                "drawdown_pct": -41.0,
            }
        }
    )

    assert result == (
        "MINT",
        "completed",
        {"outcome_status": "completed", "peak_multiple": 3.2, "drawdown_pct": -41.0},
    )
