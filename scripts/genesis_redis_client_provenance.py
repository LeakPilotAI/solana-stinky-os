"""Inactive observation checks, not Redis credentials or a write-fencing broker.

Client names alone are untrusted. Signed physical-connection observations must
match a separately inspected pinned endpoint and complete server CLIENT LIST.
All network access is supplied explicitly by a trusted read-only observer.
"""
from __future__ import annotations

import copy
import math
import re
import secrets
import threading
import time

from scripts.genesis_launch_provenance import authenticated, signed, encoded


def canonical_clients(rows):
    """Redis-py CLIENT LIST exposes decimal IDs as strings; parse losslessly."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 512:
        raise ValueError('Client inventory outside bound')
    result = []
    for row in rows:
        value = row['id']
        if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,19}', value):
            value = int(value)
        if type(value) is not int or not 1 <= value <= 2**64 - 1:
            raise ValueError('Client ID is not an exact unsigned integer')
        if not isinstance(row['name'], str) or len(row['name']) > 256:
            raise ValueError('Client name malformed')
        result.append({'id': value, 'name': row['name']})
    return result


def _physical_reader(connection, endpoint):
    socket = connection._sock
    if socket is None:
        raise ValueError('Connected physical socket required')
    timeout = socket.gettimeout()
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError('Bounded physical socket timeout required')
    if (connection.host != endpoint['host'] or connection.port != endpoint['port'] or
            socket.getpeername()[:2] != (endpoint['host'], endpoint['port'])):
        raise ValueError('Physical peer differs from pinned loopback endpoint')
    def read(*args):
        if connection._sock is not socket:
            raise ValueError('Physical connection changed')
        # Redis's normal send helpers can implicitly reconnect. Write only to
        # this retained socket; failed probes are never replayed.
        for chunk in connection.pack_command(*args):
            socket.sendall(chunk)
        result = connection.read_response()
        if connection._sock is not socket:
            raise ValueError('Physical connection changed')
        return result
    def epoch():
        raw = read('INFO', 'server')
        values = dict(line.split(b':', 1) for line in raw.splitlines() if b':' in line)
        return values[b'run_id'].decode('ascii')
    return read, epoch, socket


def server_observation(connection, endpoint, verify_endpoint):
    """Read complete CLIENT LIST on one observer socket, bracketing epoch/id.

    verify_endpoint must independently inspect the exact container/loopback route;
    no unauthenticated network reply is allowed to supply those expected pins.
    """
    if verify_endpoint() != endpoint:
        raise ValueError('Independent endpoint pins differ')
    read, epoch, _ = _physical_reader(connection, endpoint)
    before_epoch = epoch(); before_id = read('CLIENT', 'ID')
    raw = read('CLIENT', 'LIST')
    if not isinstance(raw, bytes) or len(raw) > 2 * 1024 * 1024:
        raise ValueError('Client inventory outside byte bound')
    rows = []
    for line in raw.decode('utf-8').splitlines():
        fields = {}
        for field in line.split():
            key, value = field.split('=', 1)
            if key in fields:
                raise ValueError('Repeated client metadata field')
            fields[key] = value
        rows.append({'id': fields['id'], 'name': fields['name']})
    rows = canonical_clients(rows)
    after_id = read('CLIENT', 'ID'); after_epoch = epoch()
    if before_id != after_id or before_epoch != after_epoch or verify_endpoint() != endpoint:
        raise ValueError('Observer connection, server epoch or endpoint changed')
    return {'endpoint': dict(endpoint), 'run_id': before_epoch, 'clients': rows}


def answer_connection(private_key, challenge, connection):
    """Read-only signed probe of one retained physical socket; no name setting."""
    if not isinstance(challenge, dict) or 'endpoint' not in challenge:
        raise ValueError('Pinned client challenge unavailable')
    read, epoch, socket = _physical_reader(connection, challenge['endpoint'])
    first_epoch = epoch(); first_id = read('CLIENT', 'ID')
    name = read('CLIENT', 'GETNAME')
    last_id = read('CLIENT', 'ID'); last_epoch = epoch()
    if first_epoch != last_epoch or first_id != last_id:
        raise ValueError('Redis identity changed during observation')
    body = {'kind': 'genesis-redis-client-observation-v1', 'challenge': challenge,
            'run_id': first_epoch, 'client_id': first_id,
            'socket': {'local_host': socket.getsockname()[0],
                       'local_port': socket.getsockname()[1],
                       'remote_host': socket.getpeername()[0],
                       'remote_port': socket.getpeername()[1]},
            'name': name.decode('ascii') if isinstance(name, bytes) else name}
    return signed(private_key, body)


class RedisClientObservations:
    def __init__(self, launches, endpoint, observe, observer_ids, *, native_socket, now=time.time_ns):
        if (not isinstance(endpoint, dict) or set(endpoint) != {'container_id', 'host', 'port'} or
                not re.fullmatch('[0-9a-f]{64}', endpoint['container_id']) or
                endpoint['host'] != '127.0.0.1' or type(endpoint['port']) is not int or
                not 1 <= endpoint['port'] <= 65535 or not callable(observe) or not callable(native_socket) or
                not isinstance(observer_ids, set) or not observer_ids or len(observer_ids) > 8 or
                any(type(i) is not int or i <= 0 for i in observer_ids)):
            raise ValueError('Explicit pinned read-only endpoint/observer required')
        self._launches = launches; self._endpoint = dict(endpoint)
        self._observe = observe; self._observers = set(observer_ids); self._now = now
        self._native_socket = native_socket
        self._epoch = None; self._records = {}; self._generations = {}
        self._lock = threading.RLock()
        self._view()

    def _view(self):
        view = self._observe()
        if (not isinstance(view, dict) or set(view) != {'endpoint', 'run_id', 'clients'} or
                encoded(view['endpoint']) != encoded(self._endpoint) or not isinstance(view['run_id'], str) or
                not re.fullmatch('[0-9a-f]{40}', view['run_id']) or
                not isinstance(view['clients'], list) or not 1 <= len(view['clients']) <= 512):
            raise ValueError('Redis endpoint evidence incomplete or foreign')
        if self._epoch is not None and self._epoch != view['run_id']:
            raise ValueError('Redis server epoch changed; reauthorization required')
        rows = {}
        for row in view['clients']:
            if (not isinstance(row, dict) or set(row) != {'id', 'name'} or
                    type(row['id']) is not int or row['id'] <= 0 or row['id'] in rows or
                    not isinstance(row['name'], str) or len(row['name']) > 256):
                raise ValueError('Client inventory malformed or duplicated')
            rows[row['id']] = row
        if not self._observers <= rows.keys():
            raise ValueError('Read-only observer identity lost')
        self._epoch = view['run_id']
        return rows

    def prepare(self, service, slot):
        with self._lock:
            if not isinstance(slot, str) or not re.fullmatch('[a-z0-9-]{1,40}', slot):
                raise ValueError('Connection slot unavailable')
            launch = self._launches.checked(service)
            self._view()
            key = (service, slot)
            if key not in self._records and len(self._records) >= 64:
                raise ValueError('Connection registry bound')
            generation = self._generations.get(key, 0) + 1
            challenge = {'kind': 'genesis-redis-client-challenge-v1',
                'launch': copy.deepcopy(launch['challenge']), 'slot': slot,
                'connection_generation': generation, 'endpoint': dict(self._endpoint),
                'run_id': self._epoch, 'nonce': secrets.token_hex(32),
                'expires_ns': self._now() + 30_000_000_000,
                'expected_name': 'genesis-observation-' + service + '-' + slot + '-' + secrets.token_hex(8)}
            # Preparing a new observation retires the old binding without killing
            # its socket. A still-connected old client becomes UNKNOWN in audit.
            self._records[key] = {'challenge': challenge, 'phase': 'PENDING', 'client_id': None}
            self._generations[key] = generation
            return copy.deepcopy(challenge)

    def accept(self, service, slot, proof):
        with self._lock:
            record = self._records.get((service, slot))
            try:
                launch = self._launches.checked(service)
                if record is None or record['phase'] != 'PENDING':
                    raise ValueError('Unknown, replayed or retired client observation')
                body = authenticated(launch['key'], proof)
                challenge = record['challenge']
                if (set(body) != {'kind', 'challenge', 'run_id', 'client_id', 'name', 'socket'} or
                        body['kind'] != 'genesis-redis-client-observation-v1' or
                        encoded(body['challenge']) != encoded(challenge) or
                        encoded(challenge['launch']) != encoded(launch['challenge']) or
                        self._now() >= challenge['expires_ns'] or body['run_id'] != self._epoch or
                        type(body['client_id']) is not int or body['client_id'] in self._observers or
                        body['name'] != challenge['expected_name']):
                    raise ValueError('Client launch, generation, endpoint or identity mismatch')
                socket = body['socket']
                if (not isinstance(socket, dict) or
                        set(socket) != {'local_host', 'local_port', 'remote_host', 'remote_port'} or
                        socket['local_host'] != '127.0.0.1' or
                        type(socket['local_port']) is not int or not 1 <= socket['local_port'] <= 65535 or
                        socket['remote_host'] != self._endpoint['host'] or
                        socket['remote_port'] != self._endpoint['port'] or
                        self._native_socket(launch['challenge']['owner'], socket) is not True):
                    raise ValueError('Independent native socket owner differs')
                rows = self._view()
                matching = [r for r in rows.values() if r['name'] == body['name']]
                if len(matching) != 1 or matching[0]['id'] != body['client_id']:
                    raise ValueError('Client name/id ambiguous or absent')
                if any(r['phase'] == 'ATTESTED' and r['client_id'] == body['client_id']
                       for r in self._records.values()):
                    raise ValueError('Client already attributed to another slot')
                self._launches.checked(service)
                if self._now() >= challenge['expires_ns']:
                    raise ValueError('Client verification exceeded observation deadline')
                record['client_id'] = body['client_id']; record['socket'] = dict(socket)
                record['phase'] = 'ATTESTED'
                return self.audit()
            except Exception:
                if record is not None:
                    record['phase'] = 'HOLD'
                raise ValueError('Redis observation rejected; HOLD') from None

    def audit(self):
        with self._lock:
            holds = []
            try:
                rows = self._view()
                expected = set(self._observers)
                for (service, slot), record in self._records.items():
                    launch = self._launches.checked(service)
                    challenge = record['challenge']
                    if (record['phase'] != 'ATTESTED' or encoded(challenge['launch']) != encoded(launch['challenge']) or
                            rows.get(record['client_id'], {}).get('name') != challenge['expected_name'] or
                            self._native_socket(launch['challenge']['owner'], record['socket']) is not True):
                        holds.append('UNATTESTED_OR_STALE_CLIENT'); continue
                    matching = [r for r in rows.values() if r['name'] == challenge['expected_name']]
                    if len(matching) != 1:
                        holds.append('DUPLICATE_CLIENT_NAME')
                    expected.add(record['client_id'])
                if set(rows) != expected:
                    holds.append('UNKNOWN_OR_MISSING_REDIS_CLIENT')
            except Exception:
                holds.append('ENDPOINT_OR_NATIVE_IDENTITY_UNAVAILABLE')
            return {'status': 'HOLD' if holds else 'ISOLATED_OBSERVATIONS_MATCH',
                    'holds': sorted(set(holds)), 'lifecycle_authorized': False,
                    'write_authorized': False, 'scope': 'OBSERVATION_NOT_WRITE_FENCING'}

    def review(self, service, slot, proof):
        """Fresh read-only review of an existing binding, never reconnect authority."""
        with self._lock:
            record = self._records.get((service, slot))
            launch = self._launches.checked(service)
            body = authenticated(launch['key'], proof)
            if (record is None or record['phase'] != 'ATTESTED' or
                    set(body) != {'kind','challenge','run_id','client_id','name','socket','reuse_nonce'} or
                    not isinstance(body['reuse_nonce'], str) or not re.fullmatch('[0-9a-f]{64}', body['reuse_nonce']) or
                    body['kind'] != 'genesis-redis-client-observation-v1' or
                    encoded(body['challenge']) != encoded(record['challenge']) or
                    encoded(body['challenge']['launch']) != encoded(launch['challenge']) or
                    type(body['client_id']) is not int or body['client_id'] != record['client_id'] or
                    body['run_id'] != self._epoch or body['name'] != record['challenge']['expected_name'] or
                    encoded(body['socket']) != encoded(record['socket']) or
                    self._native_socket(launch['challenge']['owner'], body['socket']) is not True):
                raise ValueError('Reused binding unverified; HOLD')
            return self.audit()
