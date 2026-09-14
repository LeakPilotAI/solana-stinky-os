from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import stinky_api.evm_reference_observation_operator as operator


@pytest.mark.asyncio
async def test_replay_fails_before_trigger(monkeypatch):
    request = SimpleNamespace(pool=SimpleNamespace(chain="ethereum-mainnet", pool_address="0xpool"), block_number=100)
    state = SimpleNamespace(last_completed_block=100, last_completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    touched = []

    async def load(*args, **kwargs): return state
    async def trigger(*args, **kwargs): touched.append(True)
    monkeypatch.setattr(operator, "load_reference_observation_runtime_state", load)
    monkeypatch.setattr(operator, "run_reference_dex_observation_if_due", trigger)

    with pytest.raises(ValueError, match="duplicate or replayed"):
        await operator.invoke_reference_dex_observation(object(), schedule=object(), request=request, now=datetime.now(timezone.utc))
    assert touched == []


@pytest.mark.asyncio
async def test_completion_recorded_only_after_triggered_run(monkeypatch):
    request = SimpleNamespace(pool=SimpleNamespace(chain="ethereum-mainnet", pool_address="0xpool"), block_number=101)
    observed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    run = SimpleNamespace(triggered=True, observed_at=observed_at)
    completed = object()
    recorded = []

    async def load(*args, **kwargs): return None
    async def trigger(*args, **kwargs): return run
    async def record(*args, **kwargs):
        recorded.append(kwargs)
        return completed
    monkeypatch.setattr(operator, "load_reference_observation_runtime_state", load)
    monkeypatch.setattr(operator, "run_reference_dex_observation_if_due", trigger)
    monkeypatch.setattr(operator, "record_reference_observation_completion", record)

    result = await operator.invoke_reference_dex_observation(object(), schedule=object(), request=request, now=observed_at)
    assert result.trigger is run
    assert result.state is completed
    assert recorded == [{"chain": "ethereum-mainnet", "pool_address": "0xpool", "block_number": 101, "completed_at": observed_at}]


@pytest.mark.asyncio
async def test_not_due_does_not_advance_state(monkeypatch):
    request = SimpleNamespace(pool=SimpleNamespace(chain="ethereum-mainnet", pool_address="0xpool"), block_number=102)
    state = SimpleNamespace(last_completed_block=101, last_completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    skipped = SimpleNamespace(triggered=False, observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    recorded = []

    async def load(*args, **kwargs): return state
    async def trigger(*args, **kwargs): return skipped
    async def record(*args, **kwargs): recorded.append(True)
    monkeypatch.setattr(operator, "load_reference_observation_runtime_state", load)
    monkeypatch.setattr(operator, "run_reference_dex_observation_if_due", trigger)
    monkeypatch.setattr(operator, "record_reference_observation_completion", record)

    result = await operator.invoke_reference_dex_observation(object(), schedule=object(), request=request, now=skipped.observed_at)
    assert result.state is state
    assert recorded == []
