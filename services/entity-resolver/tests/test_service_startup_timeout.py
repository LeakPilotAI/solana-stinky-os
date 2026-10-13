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
    assert "asyncio.wait_for(registered_task(step(), suboperation=True)" in source
    assert "timeout=ENTITY_STARTUP_STEP_TIMEOUT_SEC" in source


@pytest.mark.asyncio
@pytest.mark.parametrize('stalled',range(6))
async def test_every_schema_step_times_out_before_any_redis_admission(monkeypatch,stalled):
    from types import SimpleNamespace
    service=EntityService.__new__(EntityService);calls=[]
    async def step(index):
        calls.append(index)
        if index==stalled:await asyncio.Event().wait()
    def bound(index):
        async def run():await step(index)
        return run
    service._store=SimpleNamespace(ensure_schema=bound(0))
    service._launch_history=SimpleNamespace(ensure_schema=bound(1),ensure_reputation_projection_schema=bound(2))
    service._market_outcomes=SimpleNamespace(ensure_schema=bound(3))
    service._behavior=SimpleNamespace(ensure_schema=bound(4))
    service._relationships=SimpleNamespace(ensure_schema=bound(5))
    def forbidden(*args,**kwargs):pytest.fail('Redis connected before complete schema readiness')
    monkeypatch.setattr('entity_resolver.service.redis_client',forbidden)
    # Windows timer resolution is15.625ms: a10ms timer can fire before an
    # already-completed task resumes its waiter. Use100ms for step attribution.
    monkeypatch.setattr('entity_resolver.service.ENTITY_STARTUP_STEP_TIMEOUT_SEC',.1)
    with pytest.raises(asyncio.TimeoutError):await asyncio.wait_for(service.start(),timeout=2)
    assert calls==list(range(stalled+1))
    assert not getattr(service,'_running',False)
