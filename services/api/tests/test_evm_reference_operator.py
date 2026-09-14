from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from stinky_api.evm_reference_observation_trigger import (
    ReferenceDexObservationTriggerRequest,
    trigger_reference_dex_observation,
)


@pytest.mark.asyncio
async def test_operator_call_through_uses_exact_inputs():
    req = ReferenceDexObservationTriggerRequest(
        pool=SimpleNamespace(chain="ethereum-mainnet"),
        router_address="0xrouter",
        sources=(object(),),
        observers=(object(), object()),
        block_number=123,
        min_quorum=2,
    )
    fake_run = object()
    mocked = AsyncMock(return_value=fake_run)
    with patch(
        "stinky_api.evm_reference_observation_trigger.observe_and_persist_reference_dex_evidence",
        mocked,
    ):
        result = await trigger_reference_dex_observation(
            object(),
            request=req,
            observed_at=datetime(2026, 9, 14, 3, 1, tzinfo=timezone.utc),
        )
    assert mocked.await_count == 1
    kwargs = mocked.await_args.kwargs
    assert kwargs["pool"] is req.pool
    assert kwargs["sources"] is req.sources
    assert kwargs["observers"] is req.observers
    assert kwargs["block_number"] == 123
    assert kwargs["min_quorum"] == 2
    assert result.run is fake_run
