import asyncio
import pytest
from entity_resolver.service import EntityService

@pytest.mark.asyncio
async def test_bounded_handler_returns_after_timeout(monkeypatch):
    service = EntityService.__new__(EntityService)
    async def stuck(_msg_id, _fields):
        await asyncio.sleep(60)
    monkeypatch.setattr(service, "_handle", stuck)
    monkeypatch.setattr("entity_resolver.service.ENTITY_EVENT_HANDLE_TIMEOUT_SEC", 0.01)
    await asyncio.wait_for(service._handle_bounded("1-0", {"data": "{}"}), timeout=0.2)

def test_fresh_loop_acks_irrelevant_before_relevant_handlers():
    import inspect
    source = inspect.getsource(EntityService.run_forever)
    assert source.index("await self._redis.xack") < source.index("await self._handle_bounded")
