import copy
import json

import pytest

from scripts.genesis_launch_provenance import LaunchObservations, answer_launch, signed
from scripts.genesis_redis_client_provenance import RedisClientObservations, answer_connection, canonical_clients, server_observation


def setup():
    current = {'pid': 42, 'parent_pid': 10, 'created': '2026-10-14T20:00:00Z',
               'executable': r'C:\fixture\python.exe', 'command_sha256': 'a' * 64}
    clock = [1_000_000_000]
    launches = LaunchObservations(lambda pid: current, now=lambda: clock[0])
    frame = launches.prepare('api', current)
    launches.accept('api', answer_launch(frame, current, now=lambda: clock[0]))
    key = bytes.fromhex(json.loads(frame)['key'])
    endpoint = {'container_id': 'c' * 64, 'host': '127.0.0.1', 'port': 16601}
    view = {'endpoint': endpoint, 'run_id': 'e' * 40, 'clients': [{'id': 1, 'name': 'observer'}]}
    clients = RedisClientObservations(launches, endpoint, lambda: copy.deepcopy(view), {1},
                                     native_socket=lambda owner, socket: True, now=lambda: clock[0])
    challenge = clients.prepare('api', 'manual-queue')
    view['clients'].append({'id': 2, 'name': challenge['expected_name']})
    body = {'kind': 'genesis-redis-client-observation-v1', 'challenge': challenge,
            'run_id': view['run_id'], 'client_id': 2, 'name': challenge['expected_name'],
            'socket': {'local_host': '127.0.0.1', 'local_port': 45001,
                       'remote_host': '127.0.0.1', 'remote_port': 16601}}
    return current, clock, launches, key, view, clients, body


def test_signed_connection_matches_independent_server_inventory_without_authority():
    current, clock, launches, key, view, clients, body = setup()
    result = clients.accept('api', 'manual-queue', signed(key, body))
    assert result['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
    assert not result['lifecycle_authorized'] and not result['write_authorized']
    assert key.hex() not in json.dumps(result)


@pytest.mark.parametrize('case', ['wrong_mac', 'wrong_id', 'duplicate_name', 'wrong_name',
    'wrong_epoch', 'wrong_endpoint', 'reused_pid', 'stale_generation', 'expired', 'missing_client', 'foreign_socket'])
def test_wrong_or_ambiguous_client_claims_are_rejected(case):
    current, clock, launches, key, view, clients, body = setup()
    proof = signed(key, body)
    if case == 'wrong_mac': proof['mac'] = '0' * 64
    if case == 'wrong_id': body['client_id'] = 3; proof = signed(key, body)
    if case == 'duplicate_name': view['clients'].append({'id': 3, 'name': body['name']})
    if case == 'wrong_name': view['clients'][1]['name'] = 'foreign'
    if case == 'wrong_epoch': view['run_id'] = 'f' * 40
    if case == 'wrong_endpoint': view['endpoint']['container_id'] = 'd' * 64
    if case == 'reused_pid': current['created'] = '2026-10-14T20:00:01Z'
    if case == 'stale_generation': clients.prepare('api', 'manual-queue')
    if case == 'expired': clock[0] += 30_000_000_001
    if case == 'missing_client': view['clients'].pop()
    if case == 'foreign_socket': clients._native_socket = lambda owner, socket: False
    with pytest.raises(ValueError, match='HOLD'): clients.accept('api', 'manual-queue', proof)
    assert clients.audit()['status'] == 'HOLD'


@pytest.mark.parametrize('case', ['unknown', 'duplicate_name', 'disconnected', 'changed_launch', 'replay'])
def test_unknown_stale_or_disconnected_clients_cannot_keep_complete_attribution(case):
    current, clock, launches, key, view, clients, body = setup()
    proof = signed(key, body)
    clients.accept('api', 'manual-queue', proof)
    if case == 'unknown': view['clients'].append({'id': 3, 'name': 'foreign'})
    if case == 'duplicate_name': view['clients'].append({'id': 3, 'name': body['name']})
    if case == 'disconnected': view['clients'].pop()
    if case == 'changed_launch': launches.retire('api'); launches.prepare('api', current)
    if case == 'replay':
        with pytest.raises(ValueError): clients.accept('api', 'manual-queue', proof)
    assert clients.audit()['status'] == 'HOLD'


def test_reconnect_needs_new_generation_old_live_socket_remains_unknown():
    current, clock, launches, key, view, clients, body = setup()
    clients.accept('api', 'manual-queue', signed(key, body))
    challenge = clients.prepare('api', 'manual-queue')
    view['clients'].append({'id': 3, 'name': challenge['expected_name']})
    newer = dict(body, challenge=challenge, client_id=3, name=challenge['expected_name'])
    assert clients.accept('api', 'manual-queue', signed(key, newer))['status'] == 'HOLD'
    # Fixture removal is an observation, not CLIENT KILL or a verifier action.
    view['clients'] = [r for r in view['clients'] if r['id'] != 2]
    assert clients.audit()['status'] == 'ISOLATED_OBSERVATIONS_MATCH'


def test_signed_boolean_connection_generation_cannot_match_integer_generation():
    current, clock, launches, key, view, clients, body = setup()
    body['challenge']['connection_generation'] = True
    with pytest.raises(ValueError): clients.accept('api', 'manual-queue', signed(key, body))


def test_lost_native_reply_and_unconnected_socket_are_not_retried():
    class Connection:
        _sock = None
        def connect(self): pytest.fail('Implicit reconnect forbidden')
    with pytest.raises(ValueError): answer_connection(b'k' * 32, {}, Connection())


@pytest.mark.parametrize('value', ['01', '+1', '1.0', True, 1.4, 0, str(2**64)])
def test_client_list_parser_rejects_lossy_or_malformed_ids(value):
    with pytest.raises(ValueError): canonical_clients([{'id': value, 'name': ''}])


def test_real_client_list_decimal_ids_are_parsed_exactly_and_private_fields_omitted():
    assert canonical_clients([{'id': '12', 'name': 'observer', 'addr': 'SECRET_CANARY'}]) == [
        {'id': 12, 'name': 'observer'}]


class Socket:
    def __init__(self): self.sent = []; self.fail = False
    def getpeername(self): return ('127.0.0.1', 16601)
    def gettimeout(self): return 3
    def sendall(self, command):
        self.sent.append(command)
        if self.fail: raise OSError('fixture lost reply')


class Physical:
    host = '127.0.0.1'; port = 16601
    def __init__(self, replies): self._sock = Socket(); self.replies = iter(replies)
    def pack_command(self, *args): return [args]
    def read_response(self): return next(self.replies)
    def connect(self): pytest.fail('Implicit reconnect forbidden')


@pytest.mark.parametrize('case', ['epoch', 'connection_id', 'endpoint', 'duplicate_field', 'lost_reply'])
def test_independent_observer_rejects_partial_identity_and_never_retries(case):
    endpoint = {'container_id': 'c' * 64, 'host': '127.0.0.1', 'port': 16601}
    epoch = b'run_id:' + b'e' * 40 + b'\r\n'
    raw = b'id=1 name=observer addr=SECRET_CANARY\n'
    if case == 'duplicate_field': raw = b'id=1 id=2 name=observer\n'
    connection = Physical([epoch, 1, raw, 2 if case == 'connection_id' else 1,
                           b'run_id:' + b'f' * 40 if case == 'epoch' else epoch])
    checks = []
    def verify():
        checks.append(True)
        return dict(endpoint, port=16602) if case == 'endpoint' and len(checks) > 1 else endpoint
    if case == 'lost_reply': connection._sock.fail = True
    with pytest.raises((ValueError, OSError)):
        server_observation(connection, endpoint, verify)
    if case == 'lost_reply': assert len(connection._sock.sent) == 1


def test_replaced_physical_socket_cannot_produce_a_signed_claim():
    class Replaced(Physical):
        def read_response(self):
            result = super().read_response()
            self._sock = Socket()
            return result
    endpoint = {'container_id': 'c' * 64, 'host': '127.0.0.1', 'port': 16601}
    connection = Replaced([b'run_id:' + b'e' * 40])
    with pytest.raises(ValueError): answer_connection(b'k' * 32, {'endpoint': endpoint}, connection)


@pytest.mark.parametrize('timeout', [None, 0, float('inf')])
def test_unbounded_socket_cannot_begin_observation(timeout):
    connection = Physical([])
    connection._sock.gettimeout = lambda: timeout
    endpoint = {'container_id': 'c' * 64, 'host': '127.0.0.1', 'port': 16601}
    with pytest.raises(ValueError): answer_connection(b'k' * 32, {'endpoint': endpoint}, connection)
    assert not connection._sock.sent
