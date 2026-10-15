import copy
import json
import os
import subprocess
import sys

import pytest

from scripts.genesis_background_ownership import capture
from scripts.genesis_launch_provenance import LaunchObservations, answer_launch, descriptor, signed


def owner():
    return {'pid': 42, 'parent_pid': 10, 'created': '2026-10-14T20:00:00Z',
            'executable': r'C:\fixture\python.exe', 'command_sha256': 'a' * 64}


def setup():
    current = owner(); clock = [1_000_000_000]
    registry = LaunchObservations(lambda pid: current, now=lambda: clock[0])
    frame = registry.prepare('api', current)
    return current, clock, registry, frame


def test_launch_private_challenge_is_native_bound_and_status_has_no_secrets():
    current, clock, registry, frame = setup()
    result = registry.accept('api', answer_launch(frame, current, now=lambda: clock[0]))
    assert result['phase'] == 'ATTESTED' and not result['lifecycle_authorized']
    assert not result['write_authorized']
    private = json.loads(frame)
    assert private['key'] not in json.dumps(result)
    assert private['challenge']['nonce'] not in json.dumps(result)
    assert registry.checked('api')['challenge']['owner'] == current


@pytest.mark.parametrize('case', ['pid_reuse', 'image', 'command', 'parent', 'expired',
                                  'mac', 'copied_generation', 'copied_owner', 'heartbeat_only'])
def test_stale_copied_or_forged_launch_proofs_hold(case):
    current, clock, registry, frame = setup()
    proof = answer_launch(frame, current, now=lambda: clock[0])
    if case == 'pid_reuse': current['created'] = '2026-10-14T20:00:01Z'
    if case == 'image': current['executable'] = r'C:\foreign\python.exe'
    if case == 'command': current['command_sha256'] = 'b' * 64
    if case == 'parent': current['parent_pid'] = 99
    if case == 'expired': clock[0] += 30_000_000_001
    if case == 'mac': proof['mac'] = '0' * 64
    if case == 'copied_generation': proof['body']['generation'] += 1
    if case == 'copied_owner': proof['body']['owner']['pid'] = 43
    if case == 'heartbeat_only': proof = {'supervisor_pid': 42, 'supervisor_launch_token': 'SECRET_CANARY'}
    with pytest.raises(ValueError, match='HOLD'): registry.accept('api', proof)
    status = registry.status('api')
    assert status['phase'] == 'HOLD' and 'SECRET_CANARY' not in json.dumps(status)


def test_replay_duplicate_and_controller_restart_require_fresh_authorization():
    current, clock, registry, frame = setup()
    proof = answer_launch(frame, current, now=lambda: clock[0])
    registry.accept('api', proof)
    with pytest.raises(ValueError): registry.prepare('api', current)
    with pytest.raises(ValueError): registry.prepare('collector', current)
    with pytest.raises(ValueError): registry.accept('api', proof)
    assert registry.status('api')['phase'] == 'HOLD'
    newer = registry.prepare('api', current)
    assert json.loads(newer)['challenge']['generation'] == 2
    with pytest.raises(ValueError): registry.accept('api', proof)
    restarted = LaunchObservations(lambda pid: current, now=lambda: clock[0])
    restarted.prepare('api', current)
    with pytest.raises(ValueError): restarted.accept('api', proof)


def test_attested_process_replacement_invalidates_observation():
    current, clock, registry, frame = setup()
    registry.accept('api', answer_launch(frame, current, now=lambda: clock[0]))
    current['created'] = '2026-10-14T20:00:02Z'
    with pytest.raises(ValueError): registry.checked('api')
    assert registry.status('api')['phase'] == 'HOLD'


def test_signed_boolean_generation_is_not_equivalent_to_integer_generation():
    current, clock, registry, frame = setup()
    private = json.loads(frame); body = private['challenge']; body['generation'] = True
    with pytest.raises(ValueError):
        registry.accept('api', signed(bytes.fromhex(private['key']), body))


def test_native_verification_cannot_extend_the_authenticated_deadline():
    current, clock, registry, frame = setup()
    proof = answer_launch(frame, current, now=lambda: clock[0])
    def delayed(pid):
        clock[0] += 31_000_000_000
        return current
    registry._native = delayed
    with pytest.raises(ValueError): registry.accept('api', proof)
    assert registry.status('api')['phase'] == 'HOLD'


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows private launch fixture required')
def test_native_private_pipe_attestation_without_env_or_argv_secret():
    # Base Python avoids the venv redirector; exact retained Popen PID owns stdin.
    code = '''import sys,json
from scripts.genesis_launch_provenance import answer_launch
request=json.loads(sys.stdin.readline())
frame=bytes.fromhex(request['frame']); owner=request['owner']
if owner['pid']!=__import__('os').getpid():raise SystemExit(2)
print(json.dumps(answer_launch(frame,owner)),flush=True)
sys.stdin.readline()
'''
    proc = subprocess.Popen([sys._base_executable, '-c', code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        def native(pid):
            data = capture()
            a = next(r for r in data['before'] if r['pid'] == pid)
            b = next(r for r in data['after'] if r['pid'] == pid)
            assert descriptor(a) == descriptor(b)
            return descriptor(b)
        current = native(proc.pid)
        registry = LaunchObservations(native)
        frame = registry.prepare('api', current)
        request = json.dumps({'frame': frame.hex(), 'owner': current})
        proc.stdin.write(request + '\n'); proc.stdin.flush()
        proof = json.loads(proc.stdout.readline())
        assert registry.accept('api', proof)['phase'] == 'ATTESTED'
        observed = capture()
        row = next(r for r in observed['after'] if r['pid'] == proc.pid)
        secret = json.loads(frame)['key']
        assert all(secret not in arg for arg in row['argv'])
        assert secret not in json.dumps(registry.status('api'))
    finally:
        proc.stdin.close()
        assert proc.wait(timeout=10) == 0
