import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from scripts.genesis_background_ownership import assess, capture, listener_identity

ROOT = r'D:\Work\Project-Genesis'
PYTHON = ROOT + r'\.venv\Scripts\pythonw.exe'


def process(pid, parent, argv):
    return {'pid': pid, 'parent_pid': parent, 'argv': argv,
            'executable': argv[0], 'created': '2026-10-14T20:00:00Z',
            'command_sha256': 'a' * 64}


def fixture():
    rows = [process(10, 0, [r'C:\Windows\explorer.exe']),
            process(20, 10, [PYTHON, ROOT + r'\scripts\run_genesis_service.py', '--name', 'api']),
            process(30, 20, [PYTHON, '-m', 'stinky_api.cli'])]
    return {'before': copy.deepcopy(rows), 'after': rows, 'elapsed_seconds': 1.0,
            'sockets': [{'pid': 30, 'port': 8010, 'state': 'Listen', 'remote_port': 0}]}


def test_observed_listener_and_ancestry_never_grant_authority():
    data = fixture()
    assert listener_identity(data, 30, 8010)
    result = assess(data, ROOT)
    assert result['listeners'][0]['ancestry_match']
    assert result['owned_tree_pids_observed'] == [20, 30]
    assert result['holds'] == ['LAUNCH_PROVENANCE_UNATTESTED']
    assert result['lifecycle_authorized'] is False
    assert 'argv' not in json.dumps(result) and 'command_sha256' not in json.dumps(result)


@pytest.mark.parametrize('case,reason', [
    ('pid_reuse', 'PROCESS_IDENTITY_CHANGED'),
    ('foreign_listener', 'FOREIGN_OR_UNVERIFIED_LISTENER'),
    ('duplicate', 'MULTIPLE_SUPERVISOR_CLAIMS'),
    ('missing', 'MISSING_OR_CHANGING_PROCESS'),
    ('cycle', 'AMBIGUOUS_ANCESTRY'),
    ('future_parent', 'INVALID_CREATION_OR_PARENT_ORDER'),
    ('no_timezone', 'INVALID_CREATION_OR_PARENT_ORDER'),
    ('bad_image', 'UNVERIFIED_SUPERVISOR'),
    ('extra_args', 'UNVERIFIED_SUPERVISOR'),
    ('orphan', 'POSSIBLE_ORPHAN_OR_BYPASS'),
    ('unknown_child', 'UNVERIFIED_DESCENDANT_COMMAND'),
    ('redis_client', 'UNATTRIBUTED_REDIS_CONNECTION'),
    ('gone', 'PROCESS_DISAPPEARED_DURING_CAPTURE'),
    ('bad_socket', 'INVALID_SOCKET_EVIDENCE'),
    ('duplicate_pid', 'INVALID_NATIVE_EVIDENCE'),
    ('missing_snapshot', 'INVALID_NATIVE_EVIDENCE'),
    ('stale_snapshot', 'INVALID_NATIVE_EVIDENCE'),
    ('missing_image', 'INVALID_NATIVE_EVIDENCE'),
    ('malformed_hash', 'INVALID_NATIVE_EVIDENCE'),
])
def test_ownership_failures_hold_without_lifecycle_actions(case, reason):
    data = fixture()
    if case == 'pid_reuse': data['after'][2]['created'] = '2026-10-14T20:00:01Z'
    if case == 'foreign_listener': data['sockets'][0]['pid'] = 10
    if case == 'duplicate': data['after'].append(process(21, 10, list(data['after'][1]['argv'])))
    if case == 'missing': data['before'].pop()
    if case == 'cycle': data['after'][1]['parent_pid'] = 30
    if case == 'future_parent': data['after'][1]['created'] = '2026-10-14T20:00:10Z'
    if case == 'no_timezone': data['after'][1]['created'] = '2026-10-14T20:00:00'
    if case == 'bad_image': data['after'][1]['executable'] = r'C:\other\python.exe'
    if case == 'extra_args': data['after'][1]['argv'].append('--unexpected')
    if case == 'orphan': data['after'][2]['parent_pid'] = 10
    if case == 'unknown_child': data['after'][2]['argv'] = [PYTHON, '-c', 'SECRET_CANARY']
    if case == 'redis_client': data['sockets'].append({'pid': 10, 'port': 12345, 'state': 'Established', 'remote_port': 6380})
    if case == 'gone': data['after'].pop()
    if case == 'bad_socket': data['sockets'][0]['pid'] = '30'
    if case == 'duplicate_pid': data['after'].append(copy.deepcopy(data['after'][0]))
    if case == 'missing_snapshot': data.pop('before')
    if case == 'stale_snapshot': data['elapsed_seconds'] = 31
    if case == 'missing_image': data['after'][1].pop('executable')
    if case == 'malformed_hash': data['after'][1]['command_sha256'] = 'not-a-fingerprint'
    result = assess(data, ROOT)
    assert result['status'] == 'HOLD' and reason in result['holds']
    assert result['lifecycle_authorized'] is False
    assert 'SECRET_CANARY' not in json.dumps(result)


def test_pid_reuse_cannot_retain_socket_identity():
    data = fixture(); data['after'][2]['created'] = '2026-10-14T20:00:01Z'
    assert not listener_identity(data, 30, 8010)


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows native census required')
def test_real_child_listener_and_creation_identity(tmp_path):
    """Own fixture exits on stdin EOF; never kill or control another process."""
    portfile = tmp_path / 'port.txt'
    code = ('import socket,sys,pathlib; s=socket.socket(); '
            's.bind(("127.0.0.1",0)); s.listen(); '
            'pathlib.Path(sys.argv[1]).write_text(str(s.getsockname()[1])); '
            'sys.stdin.readline(); s.close()')
    proc = subprocess.Popen([sys.executable, '-c', code, str(portfile)], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not portfile.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert portfile.exists(), 'Fixture listener did not start'
        port = int(portfile.read_text())
        data = capture((port,))
        # Windows venv may insert a wrapper. Match the kernel socket owner and
        # prove its ancestry reaches our exact freshly spawned fixture PID.
        listener = next(s for s in data['sockets'] if s['port'] == port and s['state'] == 'Listen')
        assert listener_identity(data, listener['pid'], port)
        nodes = {p['pid']: p for p in data['after']}
        current = listener['pid']; seen = set()
        while current != proc.pid:
            assert current not in seen and current in nodes
            seen.add(current); current = nodes[current]['parent_pid']
        assert nodes[current]['parent_pid'] == os.getpid()
    finally:
        proc.stdin.close()
        assert proc.wait(timeout=10) == 0
