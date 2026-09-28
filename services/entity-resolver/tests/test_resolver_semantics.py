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


def test_completion_event_type_is_itself_measured_status() -> None:
    result = EntityService._outcome_payload(
        {
            "event_type": "post_migration.tracking_completed",
            "payload": {
                "mint": "MINT",
                "wallets_touched": 4,
                "trades_seen": 12,
            },
        }
    )

    assert result == (
        "MINT",
        "completed",
        {"wallets_touched": 4, "trades_seen": 12},
    )


def test_entity_inference_requires_complete_buyer_capture():
    from pathlib import Path

    src = Path(__file__).parents[1] / "src" / "entity_resolver"
    store = (src / "store.py").read_text(encoding="utf-8")
    relationships = (src / "relationships.py").read_text(encoding="utf-8")

    gate = "buyer_capture_complete"
    assert gate in store
    assert "JOIN migration_tracks mt ON mt.mint = a.mint" in store
    assert gate in relationships
    assert "JOIN migration_tracks mt ON mt.mint = el.mint" in relationships


def test_entity_merge_moves_launch_history_and_recomputes_launch_count():
    from pathlib import Path

    store = (
        Path(__file__).parents[1] / "src" / "entity_resolver" / "store.py"
    ).read_text(encoding="utf-8")
    start = store.index("    async def merge_entities(")
    end = store.index("    async def multi_wallet_entities(", start)
    block = store[start:end]

    assert "UPDATE entity_launches" in block
    assert "SET entity_id = :surv" in block
    assert "WHERE entity_id = :abs" in block
    assert "SELECT COUNT(*)" in block
    assert "FROM entity_launches" in block
    assert "launch_count = GREATEST(launch_count, :lc)" not in block


def test_entity_merge_invalidates_stale_behavior_fingerprints():
    from pathlib import Path

    store = (
        Path(__file__).parents[1] / "src" / "entity_resolver" / "store.py"
    ).read_text(encoding="utf-8")
    start = store.index("    async def merge_entities(")
    end = store.index("    async def multi_wallet_entities(", start)
    block = store[start:end]

    assert "DELETE FROM entity_behavior_fingerprints" in block
    assert "WHERE entity_id IN (:surv, :abs)" in block
    assert block.index("UPDATE entity_launches") < block.index(
        "DELETE FROM entity_behavior_fingerprints"
    )
