from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from entity_resolver.service import EntityService


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_capture_phase10_evidence_uses_bounded_existing_api_route(monkeypatch):
    service = EntityService.__new__(EntityService)
    service._http = SimpleNamespace(get=AsyncMock(return_value=FakeResponse()))
    service._phase10_captured_entities = set()
    monkeypatch.setattr("entity_resolver.service.settings.api_base_url", "http://127.0.0.1:8010/")

    await service._capture_phase10_evidence("MintABC", "entity-123")

    service._http.get.assert_awaited_once_with(
        "http://127.0.0.1:8010/v1/entity-graph/investigation/MintABC/calibration",
        params={"entity_id": "entity-123"},
    )


@pytest.mark.asyncio
async def test_token_migrated_records_launch_then_requests_snapshot_capture():
    service = EntityService.__new__(EntityService)
    service._redis = SimpleNamespace(xack=AsyncMock())
    entity_id = UUID("00000000-0000-0000-0000-000000000123")
    service._resolver = SimpleNamespace(ensure_deployer_observed=AsyncMock(return_value=entity_id))
    service._launch_history = SimpleNamespace(record_launch=AsyncMock(return_value=False))
    service._behavior = SimpleNamespace(refresh_entity=AsyncMock(return_value={"cadence_bucket": "UNKNOWN"}))
    service._capture_phase10_evidence = AsyncMock()

    event = {
        "event_type": "token.migrated",
        "occurred_at": "2026-09-06T00:00:00+00:00",
        "payload": {"creator": "CreatorWallet", "mint": "MintABC"},
    }

    await service._handle("123-0", {"data": json.dumps(event)})

    service._resolver.ensure_deployer_observed.assert_awaited_once_with("CreatorWallet")
    kwargs = service._launch_history.record_launch.await_args.kwargs
    assert kwargs["entity_id"] == entity_id
    assert kwargs["deployer_wallet"] == "CreatorWallet"
    assert kwargs["event_id"] == "migrated:123-0"
    assert kwargs["mint"] == "MintABC"
    service._capture_phase10_evidence.assert_awaited_once_with("MintABC", str(entity_id))
    service._redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_snapshot_capture_failure_does_not_raise_or_block_ingestion():
    service = EntityService.__new__(EntityService)
    service._http = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("api offline")))
    service._phase10_captured_entities = set()

    await service._capture_phase10_evidence("MintABC", "entity-123")

    service._http.get.assert_awaited_once()
    assert ("MintABC", "entity-123") not in service._phase10_captured_entities
