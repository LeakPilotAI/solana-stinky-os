import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from entity_resolver.service import EntityService


def test_completion_event_accepts_status_aliases() -> None:
    for key in ("outcome_status", "status", "outcome"):
        mint, status, metadata = EntityService._outcome_payload(
            {"payload": {"mint": "MINT", key: "completed"}}
        )
        assert mint == "MINT"
        assert status == "completed"
        assert metadata[key] == "completed"


def test_completion_event_requires_mint_and_status() -> None:
    assert EntityService._outcome_payload({"payload": {"status": "completed"}}) == (
        None,
        None,
        {},
    )


@pytest.mark.asyncio
async def test_changed_completion_outcome_triggers_readiness_recapture():
    service = EntityService.__new__(EntityService)
    service._redis = SimpleNamespace(xack=AsyncMock())
    entity_id = UUID("00000000-0000-0000-0000-000000000321")
    service._launch_history = SimpleNamespace(
        record_outcome=AsyncMock(return_value=True),
        get_entity_id_for_mint=AsyncMock(return_value=entity_id),
    )
    service._behavior = SimpleNamespace(
        refresh_for_mint=AsyncMock(return_value={"cadence_bucket": "WEEKLY"})
    )
    service._capture_phase10_evidence = AsyncMock()

    event = {
        "event_type": "post_migration.tracking_completed",
        "occurred_at": "2026-09-07T05:00:00+00:00",
        "payload": {"mint": "MintOutcome", "outcome_status": "RUNNER"},
    }
    await service._handle("outcome-1", {"data": json.dumps(event)})

    service._launch_history.record_outcome.assert_awaited_once()
    service._behavior.refresh_for_mint.assert_awaited_once_with("MintOutcome")
    service._launch_history.get_entity_id_for_mint.assert_awaited_once_with("MintOutcome")
    service._capture_phase10_evidence.assert_awaited_once_with(
        "MintOutcome", str(entity_id), trigger="outcome"
    )
    service._redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_unchanged_completion_outcome_does_not_create_repeat_capture():
    service = EntityService.__new__(EntityService)
    service._redis = SimpleNamespace(xack=AsyncMock())
    service._launch_history = SimpleNamespace(
        record_outcome=AsyncMock(return_value=False),
        get_entity_id_for_mint=AsyncMock(),
    )
    service._behavior = SimpleNamespace(refresh_for_mint=AsyncMock())
    service._capture_phase10_evidence = AsyncMock()

    event = {
        "event_type": "post_migration.tracking_completed",
        "payload": {"mint": "MintOutcome", "outcome_status": "RUNNER"},
    }
    await service._handle("outcome-duplicate", {"data": json.dumps(event)})

    service._behavior.refresh_for_mint.assert_not_awaited()
    service._launch_history.get_entity_id_for_mint.assert_not_awaited()
    service._capture_phase10_evidence.assert_not_awaited()
    service._redis.xack.assert_awaited_once()
