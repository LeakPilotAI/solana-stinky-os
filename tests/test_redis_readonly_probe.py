import asyncio
from types import SimpleNamespace
import pytest
from redis.asyncio import Redis
from stinky_core.transport.redis_accounting import ManagedRedis,AccountingError

def test_fixed_readonly_probe_keeps_both_identities_and_never_dispatches_mutation(monkeypatch):
    responses=iter([17,b'run_id:'+b'c'*40+b'\r\n'])
    sent=[];packed=[]
    async def initialize(client):return client
    async def send(payload,**kwargs):sent.append((payload,kwargs))
    async def read():return next(responses)
    def pack(commands):packed.extend(commands);return [b'fixed-read-only-frame']
    client=ManagedRedis.from_url('redis://fixture',single_connection_client=True)
    client.connection=SimpleNamespace(pack_commands=pack,send_packed_command=send,read_response=read)
    monkeypatch.setattr(Redis,'initialize',initialize)
    try:
        assert asyncio.run(client._binding_observation())==(17,{'run_id':'c'*40})
        assert packed==[('CLIENT','ID'),('INFO','server')]
        assert sent==[([b'fixed-read-only-frame'],{'check_health':False})]
        with pytest.raises(AccountingError):client.pipeline()
    finally:client.connection=None

def test_probe_failure_holds_before_any_intent(monkeypatch):
    client=ManagedRedis.from_url('redis://fixture',single_connection_client=True)
    client.runtime=SimpleNamespace(held=False)
    async def failed(self):raise ConnectionError('Synthetic closed read-only connection')
    monkeypatch.setattr(ManagedRedis,'_binding_observation',failed)
    with pytest.raises(ConnectionError):asyncio.run(client._physical_binding())
    assert client.runtime.held
