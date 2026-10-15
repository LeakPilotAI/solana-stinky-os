"""Real Redis pools; native callback mocked here, separately native-certified."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.genesis_launch_provenance import LaunchObservations, answer_launch
from scripts.genesis_redis_client_provenance import RedisClientObservations, server_observation
from scripts.genesis_redis_pool_observation import PoolObservations, PhysicalSession, processed_receipt

CID = os.environ.get('GENESIS_OBSERVATION_REDIS_CONTAINER')


@pytest.fixture
def controller():
    if not CID: pytest.skip('Explicit isolated Redis fixture required')
    import redis
    record = json.loads(subprocess.check_output(['docker', 'inspect', CID], timeout=10))[0]
    assert record['Id'] == CID and record['Name'].startswith('/genesis-background-auth-')
    assert record['Config']['Labels'].get('genesis.audit') == 'background-auth-provenance-v1'
    assert not any(m.get('Type') in ('volume', 'bind') for m in record['Mounts'])
    binding = record['HostConfig']['PortBindings']['6379/tcp']
    assert len(binding) == 1 and binding[0]['HostIp'] == '127.0.0.1'
    endpoint = {'container_id': CID, 'host': '127.0.0.1', 'port': int(binding[0]['HostPort'])}
    observer = redis.Redis(host=endpoint['host'], port=endpoint['port'],
        single_connection_client=True, socket_timeout=3)
    observer_id = observer.client_id()
    def verify():
        r = json.loads(subprocess.check_output(['docker', 'inspect', CID], timeout=10))[0]
        assert r['Id'] == CID and r['State']['Running'] and r['HostConfig']['PortBindings']['6379/tcp'] == binding
        return endpoint
    def make(service, role, asynchronous):
        owner = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'created': '2026-10-14T20:00:00Z',
                 'executable': 'isolated-pool-fixture', 'command_sha256': 'a' * 64}
        launches = LaunchObservations(lambda pid: owner)
        frame = launches.prepare(service, owner); key = bytes.fromhex(json.loads(frame)['key'])
        launches.accept(service, answer_launch(frame, owner))
        clients = RedisClientObservations(launches, endpoint,
            lambda: server_observation(observer.connection, endpoint, verify), {observer_id},
            native_socket=lambda owner, socket: True)
        def exchange(proof):
            method = clients.review if 'reuse_nonce' in proof['body'] else clients.accept
            return processed_receipt(key, proof, method(service, proof['body']['challenge']['slot'], proof))
        async def async_exchange(proof): return exchange(proof)
        def prepare(role, slot):
            challenge = clients.prepare(service, slot)
            return PhysicalSession(key, challenge, async_exchange if asynchronous else exchange)
        return PoolObservations(service=service, roles={role}, endpoint=endpoint, prepare=prepare,
                                asynchronous=asynchronous), clients, endpoint
    yield make
    observer.close()


@pytest.mark.parametrize('service,role', [('event-log','redis-streams'), ('api','api-manual-queue'),
    ('collector','collector-consumer'), ('entities','entity-consumer'),
    ('sentinel','sentinel-manual-consumer'), ('discord','discord-alerts')])
def test_actual_async_factory_roles_register_physical_connections(controller, monkeypatch, service, role):
    from stinky_core.transport import redis_accounting as accounting
    factory, clients, endpoint = controller(service, role, True)
    monkeypatch.setattr(accounting, 'CLIENT_OBSERVATIONS', factory)
    monkeypatch.setattr(accounting, 'FACTORY', accounting.ClientFactory())
    monkeypatch.delenv('GENESIS_PROTECTED_REDIS_GRANT', raising=False)
    async def run():
        client = accounting.redis_client(f"redis://127.0.0.1:{endpoint['port']}/0", role=role)
        try:
            assert await client.ping()
            assert await client.ping()  # Same pool/socket cannot inherit another role.
            assert factory.counter == 1
            assert clients.audit()['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
            await client.connection_pool.disconnect()
            with pytest.raises(ValueError, match='fresh authenticated generation'): await client.ping()
        finally: await client.aclose(); await client.connection_pool.disconnect()
    asyncio.run(run())


def test_sync_pool_registration_reuse_and_reconnect_hold(controller):
    factory, clients, endpoint = controller('api', 'api-manual-queue', False)
    client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='api-manual-queue')
    try:
        assert client.ping() and client.ping()
        assert factory.counter == 1 and clients.audit()['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
        client.connection_pool.disconnect()
        with pytest.raises(ValueError): client.ping()
    finally: client.close(); client.connection_pool.disconnect()


def test_foreign_role_and_accounting_conflict_cannot_fallback(controller, monkeypatch):
    from stinky_core.transport import redis_accounting as accounting
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    with pytest.raises(ValueError): factory.from_url('redis://127.0.0.1:1', role='entity-consumer')
    monkeypatch.setattr(accounting, 'CLIENT_OBSERVATIONS', factory)
    monkeypatch.setattr(accounting, 'FACTORY', accounting.ClientFactory())
    monkeypatch.setenv('GENESIS_PROTECTED_REDIS_GRANT', 'fixture-conflict-not-a-secret')
    with pytest.raises(accounting.AccountingError): accounting.redis_client('redis://127.0.0.1:1', role='api-manual-queue')


def test_multiple_async_physical_connections_each_register(controller):
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    async def run():
        client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='api-manual-queue')
        first = second = None
        try:
            first = await client.connection_pool.get_connection()
            second = await client.connection_pool.get_connection()
            assert first is not second and factory.counter == 2
            assert first.observation.challenge['slot'] != second.observation.challenge['slot']
            assert clients.audit()['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
        finally:
            if first: await client.connection_pool.release(first)
            if second: await client.connection_pool.release(second)
            await client.aclose(); await client.connection_pool.disconnect()
    asyncio.run(run())


def test_unknown_live_client_prevents_pool_registration(controller):
    import redis
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    foreign = redis.Redis(host=endpoint['host'], port=endpoint['port'], socket_timeout=3)
    foreign.ping()
    async def run():
        client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='api-manual-queue')
        try:
            with pytest.raises(ValueError): await client.ping()
            assert clients.audit()['status'] == 'HOLD'
        finally: await client.aclose(); await client.connection_pool.disconnect()
    try: asyncio.run(run())
    finally: foreign.close(); foreign.connection_pool.disconnect()


def test_issued_legacy_factory_cannot_be_hot_patched(controller, monkeypatch):
    from stinky_core.transport import redis_accounting as accounting
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    legacy = accounting.ClientFactory(); legacy.issued = True
    monkeypatch.setattr(accounting, 'FACTORY', legacy)
    monkeypatch.setattr(accounting, 'CLIENT_OBSERVATIONS', factory)
    with pytest.raises(accounting.AccountingError): accounting.redis_client('redis://127.0.0.1:1', role='api-manual-queue')


@pytest.mark.parametrize('query', ['max_connections=100', 'db=1', 'socket_timeout=20',
                                  'health_check_interval=1', 'retry_on_timeout=True'])
def test_url_options_cannot_override_observation_scope(controller, query):
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    with pytest.raises(ValueError):
        factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0?{query}", role='api-manual-queue')


@pytest.mark.parametrize('timeout', [10, None])
def test_async_application_read_timeouts_are_preserved(controller, timeout):
    factory, clients, endpoint = controller('collector', 'collector-consumer', True)
    async def run():
        client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='collector-consumer',
                                  socket_timeout=timeout, socket_connect_timeout=5)
        try:
            assert client.connection_pool.connection_kwargs['socket_timeout'] == timeout
            assert client.connection_pool.connection_kwargs['socket_connect_timeout'] == 5
            assert await client.ping()
        finally: await client.aclose(); await client.connection_pool.disconnect()
    asyncio.run(run())


def test_simultaneous_unregistered_connections_do_not_all_pass_partial_attribution(controller):
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    async def run():
        ready = asyncio.Event(); arrivals = 0
        original = factory.prepare
        def prepare(role, slot):
            session = original(role, slot); exchange = session.exchange
            async def barrier(proof):
                nonlocal arrivals
                arrivals += 1
                if arrivals == 2: ready.set()
                await asyncio.wait_for(ready.wait(), 5)
                return await exchange(proof)
            session.exchange = barrier
            return session
        factory.prepare = prepare
        client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='api-manual-queue')
        try:
            results = await asyncio.gather(client.ping(), client.ping(), return_exceptions=True)
            assert arrivals == 2
            assert any(isinstance(result, ValueError) for result in results)
            assert all(result is True or isinstance(result, ValueError) for result in results)
        finally: await client.aclose(); await client.connection_pool.disconnect()
    asyncio.run(run())


def test_retired_launch_cannot_continue_using_a_bound_pool_socket(controller):
    factory, clients, endpoint = controller('api', 'api-manual-queue', True)
    async def run():
        client = factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0", role='api-manual-queue')
        try:
            assert await client.ping()
            clients._launches.retire('api')
            with pytest.raises(ValueError): await client.ping()
        finally: await client.aclose(); await client.connection_pool.disconnect()
    asyncio.run(run())


def test_processed_receipt_cannot_be_replayed_for_a_fresh_reuse_nonce():
    from scripts.genesis_launch_provenance import signed
    key = b'k' * 32
    original = signed(key, {'kind': 'fixture', 'reuse_nonce': 'a' * 64})
    newer = signed(key, {'kind': 'fixture', 'reuse_nonce': 'b' * 64})
    receipt = processed_receipt(key, original, {'status': 'ISOLATED_OBSERVATIONS_MATCH'})
    session = PhysicalSession(key, {}, lambda proof: receipt)
    session.receipt(original, receipt)
    with pytest.raises(ValueError): session.receipt(newer, receipt)
