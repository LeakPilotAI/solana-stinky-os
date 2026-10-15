"""Explicitly opted-in, disposable Redis + real native child observations only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.genesis_background_ownership import capture
from scripts.genesis_launch_provenance import LaunchObservations, descriptor
from scripts.genesis_redis_client_provenance import RedisClientObservations, server_observation

CID = os.environ.get('GENESIS_OBSERVATION_REDIS_CONTAINER')
pytestmark = pytest.mark.skipif(os.name != 'nt' or not CID,
                                reason='Explicit isolated Windows/Redis fixture required')


def test_real_native_child_redis_id_epoch_reconnect_and_duplicate_name():
    import redis
    record = json.loads(subprocess.check_output(['docker', 'inspect', CID], timeout=10))[0]
    assert record['Id'] == CID and record['Name'].startswith('/genesis-background-auth-')
    assert record['Config']['Labels'].get('genesis.audit') == 'background-auth-provenance-v1'
    assert record['Image'] == 'sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99'
    assert record['State']['Running'] is True
    assert all(m.get('Name', '').startswith('project-genesis_') is False for m in record['Mounts'])
    bindings = record['HostConfig']['PortBindings']['6379/tcp']
    assert len(bindings) == 1 and bindings[0]['HostIp'] == '127.0.0.1'
    port = int(bindings[0]['HostPort'])
    endpoint = {'container_id': CID, 'host': '127.0.0.1', 'port': port}
    observer = redis.Redis(host='127.0.0.1', port=port, single_connection_client=True,
                           socket_timeout=3, socket_connect_timeout=3)
    observer_id = observer.client_id()
    def verify_endpoint():
        current = json.loads(subprocess.check_output(['docker', 'inspect', CID], timeout=10))[0]
        assert current['Id'] == CID and current['State']['Running'] is True
        assert current['HostConfig']['PortBindings']['6379/tcp'] == bindings
        return endpoint
    def observe():
        return server_observation(observer.connection, endpoint, verify_endpoint)
    child_code = '''import sys,json,os,redis
from scripts.genesis_launch_provenance import answer_launch
from scripts.genesis_redis_client_provenance import answer_connection
request=json.loads(sys.stdin.readline()); frame=bytes.fromhex(request['frame'])
owner=request['owner']
if owner['pid']!=os.getpid():raise SystemExit(2)
print(json.dumps(answer_launch(frame,owner)),flush=True)
key=bytes.fromhex(json.loads(frame)['key']); connection=None
try:
 for line in sys.stdin:
  request=json.loads(line)
  if request['action']=='close':
   if connection:connection.disconnect()
   connection=None;print('CLOSED',flush=True);continue
  challenge=request['challenge']
  if connection:connection.disconnect()
  endpoint=challenge['endpoint']
  connection=redis.Connection(host=endpoint['host'],port=endpoint['port'],
   client_name=challenge['expected_name'],socket_timeout=3,socket_connect_timeout=3)
  connection.connect()
  print(json.dumps(answer_connection(key,challenge,connection)),flush=True)
finally:
 if connection:connection.disconnect()
'''
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root), str(root / '.venv/Lib/site-packages')]))
    proc = subprocess.Popen([sys._base_executable, '-c', child_code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    foreign = None
    try:
        def native(pid):
            data = capture()
            a = next(r for r in data['before'] if r['pid'] == pid)
            b = next(r for r in data['after'] if r['pid'] == pid)
            assert descriptor(a) == descriptor(b)
            return descriptor(b)
        current = native(proc.pid); launches = LaunchObservations(native)
        frame = launches.prepare('api', current)
        def send(value): proc.stdin.write(json.dumps(value) + '\n'); proc.stdin.flush()
        send({'frame': frame.hex(), 'owner': current})
        assert launches.accept('api', json.loads(proc.stdout.readline()))['phase'] == 'ATTESTED'
        def native_socket(owner, socket):
            data = capture((port,))
            a = next(r for r in data['before'] if r['pid'] == owner['pid'])
            b = next(r for r in data['after'] if r['pid'] == owner['pid'])
            if descriptor(a) != owner or descriptor(b) != owner:
                return False
            return any(r['pid'] == owner['pid'] and r['state'] == 'Established' and
                       r['address'] == socket['local_host'] and r['port'] == socket['local_port'] and
                       r['remote_address'] == socket['remote_host'] and r['remote_port'] == socket['remote_port']
                       for r in data['sockets'])
        clients = RedisClientObservations(launches, endpoint, observe, {observer_id}, native_socket=native_socket)
        challenge = clients.prepare('api', 'manual-queue')
        send({'action': 'observe', 'challenge': challenge})
        proof = json.loads(proc.stdout.readline())
        assert clients.accept('api', 'manual-queue', proof)['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
        first_id = proof['body']['client_id']
        foreign = redis.Redis(host='127.0.0.1', port=port, single_connection_client=True,
                              client_name=challenge['expected_name'], socket_timeout=3)
        foreign.ping()
        assert clients.audit()['status'] == 'HOLD'
        foreign.close(); foreign = None
        assert clients.audit()['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
        send({'action': 'close'}); assert proc.stdout.readline().strip() == 'CLOSED'
        assert clients.audit()['status'] == 'HOLD'
        newer = clients.prepare('api', 'manual-queue')
        assert newer['connection_generation'] == challenge['connection_generation'] + 1
        send({'action': 'observe', 'challenge': newer})
        proof = json.loads(proc.stdout.readline())
        assert proof['body']['client_id'] != first_id
        assert clients.accept('api', 'manual-queue', proof)['status'] == 'ISOLATED_OBSERVATIONS_MATCH'
        assert clients.audit()['write_authorized'] is False
    finally:
        if foreign: foreign.close()
        proc.stdin.close()
        assert proc.wait(timeout=10) == 0
        observer.close()
