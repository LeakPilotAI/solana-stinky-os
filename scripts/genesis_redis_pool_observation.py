"""Inactive per-physical-connection bridge; no env activation or write fence."""
import asyncio
import hashlib
import math
import os
import secrets
import threading

from scripts.genesis_launch_provenance import authenticated, encoded, signed
from scripts.genesis_redis_client_provenance import answer_connection

SERVICE_ROLES = {
    'event-log': {'redis-streams'}, 'api': {'redis-streams', 'api-manual-queue'},
    'sentinel': {'redis-streams', 'sentinel-manual-consumer'},
    'collector': {'redis-streams', 'collector-consumer'},
    'entities': {'redis-streams', 'entity-consumer'}, 'discord': {'discord-alerts'},
}


def processed_receipt(key, proof, result):
    return signed(key, {'kind': 'genesis-client-observation-processed-v1',
        'target': hashlib.sha256(encoded(proof)).hexdigest(),
        'matched': result.get('status') == 'ISOLATED_OBSERVATIONS_MATCH',
        'lifecycle_authorized': False, 'write_authorized': False})


async def answer_async_connection(key, challenge, connection):
    writer = connection._writer; reader = connection._reader
    if writer is None or reader is None or writer.is_closing():
        raise ValueError('Connected async physical stream required')
    endpoint = challenge['endpoint']
    peer = writer.get_extra_info('peername'); local = writer.get_extra_info('sockname')
    if peer[:2] != (endpoint['host'], endpoint['port']):
        raise ValueError('Async physical endpoint differs')
    async def read(*args):
        if connection._writer is not writer or connection._reader is not reader:
            raise ValueError('Async connection changed')
        writer.writelines(connection.pack_command(*args))
        await asyncio.wait_for(writer.drain(), 3)
        result = await asyncio.wait_for(connection.read_response(disable_decoding=True), 3)
        if connection._writer is not writer or connection._reader is not reader:
            raise ValueError('Async connection changed')
        return result
    async def epoch():
        raw = await read('INFO', 'server')
        return dict(line.split(b':', 1) for line in raw.splitlines() if b':' in line)[b'run_id'].decode()
    first = await epoch(); ident = await read('CLIENT', 'ID'); name = await read('CLIENT', 'GETNAME')
    last_id = await read('CLIENT', 'ID'); last = await epoch()
    if first != last or ident != last_id:
        raise ValueError('Async connection/server changed during probe')
    return signed(key, {'kind': 'genesis-redis-client-observation-v1', 'challenge': challenge,
        'run_id': first, 'client_id': ident, 'name': name.decode() if isinstance(name, bytes) else name,
        'socket': {'local_host': local[0], 'local_port': local[1],
                   'remote_host': peer[0], 'remote_port': peer[1]}})


class PhysicalSession:
    def __init__(self, key, challenge, exchange):
        if not isinstance(key, bytes) or len(key) != 32 or not callable(exchange):
            raise ValueError('Private connection session required')
        self.key = key; self.challenge = challenge; self.exchange = exchange
        self.bound = False; self.identity = None
        self.failed = False
        self.body = None

    def receipt(self, proof, reply):
        expected = {'kind': 'genesis-client-observation-processed-v1',
            'target': hashlib.sha256(encoded(proof)).hexdigest(), 'matched': True,
            'lifecycle_authorized': False, 'write_authorized': False}
        if encoded(authenticated(self.key, reply)) != encoded(expected):
            raise ValueError('Connection processing not independently acknowledged; HOLD')
    def checked(self, proof, reply):
        self.receipt(proof, reply)
        self.bound = True; self.body = proof['body']

    def reuse_proof(self, proof):
        if encoded(proof['body']) != encoded(self.body):
            raise ValueError('Reused connection identity changed; HOLD')
        body = dict(proof['body'], reuse_nonce=secrets.token_hex(32))
        return signed(self.key, body)

    def sync_reuse(self, connection):
        try:
            proof = self.reuse_proof(answer_connection(self.key, self.challenge, connection))
            self.receipt(proof, self.exchange(proof))
        except Exception:
            self.failed = True
            raise

    async def async_reuse(self, connection):
        try:
            proof = self.reuse_proof(await answer_async_connection(self.key, self.challenge, connection))
            self.receipt(proof, await asyncio.wait_for(self.exchange(proof), 30))
        except BaseException:
            self.failed = True
            raise

    def sync(self, connection):
        try:
            proof = answer_connection(self.key, self.challenge, connection)
            self.checked(proof, self.exchange(proof))
            self.identity = connection._sock
        except Exception:
            self.failed = True
            raise

    async def asynchronous(self, connection):
        try:
            proof = await answer_async_connection(self.key, self.challenge, connection)
            reply = await asyncio.wait_for(self.exchange(proof), 30)
            self.checked(proof, reply)
            self.identity = connection._writer
        except BaseException:
            self.failed = True
            raise


class PoolObservations:
    """Trusted bootstrap supplies private sessions; each connection gets its own."""
    def __init__(self, *, service, roles, endpoint, prepare, asynchronous=True):
        if not callable(prepare) or not roles or not set(roles) <= SERVICE_ROLES.get(service, set()):
            raise ValueError('Explicit observation roles/controller required')
        self.service = service; self.roles = frozenset(roles); self.endpoint = dict(endpoint)
        self.prepare = prepare; self.asynchronous = asynchronous; self.pid = os.getpid(); self.counter = 0
        self.lock = threading.Lock()

    def from_url(self, url, *, role, **kwargs):
        if role not in self.roles or os.getpid() != self.pid or 'connection_pool' in kwargs:
            raise ValueError('Foreign role/process/pool; HOLD')
        from redis.backoff import NoBackoff
        if self.asynchronous:
            from redis.asyncio import Redis
            from redis.asyncio.connection import Connection
            from redis.asyncio.retry import Retry
        else:
            from redis import Redis
            from redis.connection import Connection
            from redis.retry import Retry
        factory = self
        class ObservedConnection(Connection):
            def __init__(self, *args, **options):
                with factory.lock:
                    factory.counter += 1
                    if factory.counter > 64:
                        raise ValueError('Physical observation registry bound')
                    slot = role + '-' + str(factory.counter)
                session = factory.prepare(role, slot)
                if (not isinstance(session, PhysicalSession) or
                        session.challenge['launch']['service'] != factory.service or
                        session.challenge['launch']['owner']['pid'] != os.getpid() or
                        session.challenge['slot'] != slot or session.challenge['endpoint'] != factory.endpoint):
                    raise ValueError('Physical session role/native identity mismatch')
                self.observation = session
                options['client_name'] = session.challenge['expected_name']
                super().__init__(*args, **options)
            def sync_connect(self):
                session = self.observation
                if os.getpid() != factory.pid or session.failed:
                    raise ValueError('Inherited pool owner differs')
                if session.bound:
                    if self._sock is not session.identity or self._sock is None:
                        raise ValueError('Reconnect needs a fresh authenticated generation')
                    session.sync_reuse(self)
                    return
                super().connect()
                session.sync(self)
            async def async_connect(self):
                session = self.observation
                if os.getpid() != factory.pid or session.failed:
                    raise ValueError('Inherited pool owner differs')
                if session.bound:
                    if self._writer is not session.identity or self._writer is None or self._writer.is_closing():
                        raise ValueError('Reconnect needs a fresh authenticated generation')
                    await session.async_reuse(self)
                    return
                await super().connect()
                await session.asynchronous(self)
        ObservedConnection.connect = ObservedConnection.async_connect if self.asynchronous else ObservedConnection.sync_connect
        kwargs.update(connection_class=ObservedConnection, retry=Retry(NoBackoff(), 0),
                      retry_on_timeout=False, health_check_interval=0)
        kwargs.setdefault('socket_timeout', 3)
        kwargs.setdefault('socket_connect_timeout', 3)
        kwargs.setdefault('max_connections', 8)
        if type(kwargs['max_connections']) is not int or not 1 <= kwargs['max_connections'] <= 8:
            raise ValueError('Pool capacity outside observation bound')
        try:
            client = Redis.from_url(url, **kwargs)
        except Exception:
            raise ValueError('Redis URL/pool initialization rejected; HOLD') from None
        config = client.connection_pool.connection_kwargs
        if (client.connection_pool.connection_class is not ObservedConnection or
                config.get('host') != self.endpoint['host'] or int(config.get('port', 0)) != self.endpoint['port'] or
                config.get('db', 0) != 0 or not 1 <= client.connection_pool.max_connections <= 8 or
                config.get('health_check_interval') != 0 or
                config.get('retry_on_timeout') or config['retry'].get_retries() != 0):
            raise ValueError('URL/pool overrides observation scope; HOLD')
        for option in ('socket_timeout', 'socket_connect_timeout'):
            value = config.get(option)
            if option == 'socket_timeout' and value is None and self.asynchronous:
                continue  # Async metadata probes have their own 3s deadlines.
            maximum = 10 if self.asynchronous or option == 'socket_connect_timeout' else 5
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError('URL overrides bounded observation timing')
        return client
