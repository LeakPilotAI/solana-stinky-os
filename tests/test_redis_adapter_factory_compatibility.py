import asyncio,json
from stinky_core.transport.redis_streams import RedisStreamsTransport
from stinky_api import track
from stinky_core.transport import redis_accounting as accounting


def test_shared_transport_default_off_preserves_exact_legacy_client_options(monkeypatch):
    calls=[]
    class Client:
        async def ping(self):return True
    def factory(url,**kwargs):calls.append((url,kwargs));return Client()
    from redis.asyncio import Redis
    monkeypatch.setattr(Redis,'from_url',factory)
    monkeypatch.setattr(accounting,'FACTORY',accounting.ClientFactory())
    transport=RedisStreamsTransport(redis_url='redis://fixture-only/0')
    asyncio.run(transport.connect())
    assert calls==[('redis://fixture-only/0',{'decode_responses':False,'socket_connect_timeout':2,'socket_timeout':3,'retry_on_timeout':True,'health_check_interval':15,'socket_keepalive':True})]
    assert accounting.FACTORY.runtime is None


def test_actual_api_queue_path_remains_legacy_without_activation(monkeypatch):
    calls=[];payloads=[]
    class Client:
        async def lpush(self,key,value):payloads.append((key,json.loads(value)));return 1
        async def llen(self,key):return len(payloads)
        async def aclose(self):calls.append('closed')
    def factory(url,**kwargs):calls.append((url,kwargs));return Client()
    monkeypatch.setattr(track.aioredis,'from_url',factory)
    monkeypatch.setattr(track.settings,'redis_url','redis://fixture-only/0')
    monkeypatch.setattr(accounting,'FACTORY',accounting.ClientFactory())
    mint='1'*40+'pump'
    response=asyncio.run(track.enqueue_manual_track(track.TrackRequest(mint=mint)))
    assert response['ok'] and response['queue_len']==1
    assert payloads==[('stinky.manual_tracks',{'mint':mint,'pool':None,'note':'manual'})]
    assert calls==[('redis://fixture-only/0',{'decode_responses':True}),'closed']
    assert accounting.FACTORY.runtime is None
