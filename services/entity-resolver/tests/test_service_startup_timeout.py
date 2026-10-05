import asyncio
import pytest
from entity_resolver.service import EntityService

@pytest.mark.asyncio
async def test_startup_schema_step_is_bounded(monkeypatch):
    service=EntityService.__new__(EntityService)
    async def stuck(): await asyncio.sleep(60)
    class Obj: pass
    for name in ("_store","_launch_history","_market_outcomes","_behavior","_relationships"):
        setattr(service,name,Obj())
    service._store.ensure_schema=stuck
    service._launch_history.ensure_schema=stuck
    service._launch_history.ensure_reputation_projection_schema=stuck
    service._market_outcomes.ensure_schema=stuck
    service._behavior.ensure_schema=stuck
    service._relationships.ensure_schema=stuck
    monkeypatch.setattr("entity_resolver.service.ENTITY_STARTUP_STEP_TIMEOUT_SEC",0.01)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(service.start(),timeout=0.2)

def test_startup_contract_names_every_schema_step():
    import inspect
    source=inspect.getsource(EntityService.start)
    for name in ("entity_store_schema","launch_history_schema","reputation_projection_schema","market_outcomes_schema","behavior_schema","relationships_schema"):
        assert name in source
    assert "asyncio.wait_for(step()" in source
