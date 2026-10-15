import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.genesis_background_ownership import SERVICES
from scripts.genesis_launch_provenance import LaunchObservations, answer_launch, encoded, signed
from scripts.genesis_child_observation import ChildObservations, PrivateChildReceiver, dispatch_python_service
from scripts.genesis_background_ownership import MODULES


def native(pid):
    import hashlib
    command = ("$ErrorActionPreference='Stop';$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(int(pid)) + "';"
               "if (!$p) {throw 'Missing native owner'};"
               "@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;"
               "created=$p.CreationDate.ToUniversalTime().ToString('o');"
               "executable=[string]$p.ExecutablePath;command=[string]$p.CommandLine}|ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                            capture_output=True, timeout=10, check=True)
    row = json.loads(result.stdout.decode('utf-8-sig'))
    row['command_sha256'] = hashlib.sha256(row.pop('command').encode()).hexdigest()
    return row


def setup(service='api'):
    parent = {'pid': 123, 'parent_pid': 1, 'created': '2026-10-14T20:00:00Z',
              'executable': 'fixture-parent', 'command_sha256': 'a'*64}
    child = dict(parent, pid=os.getpid(), parent_pid=123, executable='fixture-child')
    rows = {parent['pid']: parent, child['pid']: child}
    native = lambda pid: dict(rows[pid])
    ancestry = lambda c, p: c['parent_pid'] == p['pid']
    launches = LaunchObservations(native)
    frame = launches.prepare(service, parent)
    launches.accept(service, answer_launch(frame, parent))
    controller = ChildObservations(launches, native=native, ancestry=ancestry)
    frame = controller.prepare(service, child)
    receiver = PrivateChildReceiver(service=service, launch=launches.checked(service)['challenge'],
                                    native=native, ancestry=ancestry)
    return rows, launches, controller, receiver, frame


@pytest.mark.parametrize('service', SERVICES)
def test_all_service_bindings_require_processed_private_receipt(service):
    rows, launches, controller, receiver, frame = setup(service)
    proof = receiver.receive(frame)
    installed = []
    assert receiver.phase == 'AWAITING_PROCESSED' and not installed
    reply = controller.accept(service, proof)
    status = receiver.complete(reply, lambda: installed.append(True) or True)
    assert installed == [True] and receiver.phase == 'OBSERVED'
    controller.confirm(service, receiver.completion)
    assert controller.checked(service)['owner']['pid'] == os.getpid()
    assert not status['write_authorized'] and not status['lifecycle_authorized']
    assert json.loads(frame)['key'] not in json.dumps(status)
    assert receiver.key is None


@pytest.mark.parametrize('failure', ['parent', 'child', 'restart', 'replay', 'receipt',
                                   'install', 'duplicate', 'other-service', 'timeout', 'clock-order'])
def test_failures_hold_and_do_not_dispatch(failure):
    rows, launches, controller, receiver, frame = setup()
    proof = receiver.receive(frame); calls = []
    if failure == 'parent': rows[123]['created'] = '2026-10-14T20:00:01Z'
    if failure == 'child': rows[os.getpid()]['created'] = '2026-10-14T20:00:01Z'
    if failure == 'restart': launches.retire('api')
    if failure == 'clock-order': rows[os.getpid()]['created'] = '2026-10-14T19:59:59Z'
    if failure == 'timeout': controller.now = lambda: 2**63
    if failure in ('parent', 'child', 'restart', 'timeout', 'clock-order'):
        with pytest.raises(ValueError, match='HOLD'): controller.accept('api', proof)
        assert controller.records['api']['phase'] == 'HOLD'
    elif failure == 'duplicate':
        with pytest.raises(ValueError): controller.prepare('api', rows[os.getpid()])
    elif failure == 'other-service':
        with pytest.raises(ValueError): controller.accept('entities', proof)
    elif failure == 'replay':
        controller.accept('api', proof)
        with pytest.raises(ValueError, match='HOLD'): controller.accept('api', proof)
        with pytest.raises(ValueError): controller.checked('api')
    else:
        reply = controller.accept('api', proof)
        if failure == 'receipt': reply['body']['target'] = 'b'*64
        def install():
            if failure == 'install': raise RuntimeError('SECRET_CANARY')
            calls.append(True); return True
        with pytest.raises(ValueError, match='HOLD') as error: receiver.complete(reply, install)
        assert 'SECRET_CANARY' not in str(error.value) and receiver.phase == 'HOLD'
    assert not calls


@pytest.mark.parametrize('failure', ['foreign-service', 'parent', 'oversize', 'malformed', 'replay'])
def test_receiver_rejects_before_install(failure):
    rows, launches, controller, receiver, frame = setup()
    if failure == 'foreign-service': receiver.service = 'web'; receiver.launch = dict(receiver.launch, service='web')
    if failure == 'parent': rows[os.getpid()]['parent_pid'] = 456
    if failure == 'oversize': frame = b' ' * 16385
    if failure == 'malformed': frame = b'{}'
    if failure == 'replay': receiver.receive(frame)
    with pytest.raises(ValueError, match='HOLD'): receiver.receive(frame)
    assert receiver.phase == 'HOLD' and receiver.key is None


def test_controller_does_not_accept_proof_as_installation():
    rows, launches, controller, receiver, frame = setup()
    controller.accept('api', receiver.receive(frame))
    with pytest.raises(ValueError): controller.checked('api')
    assert controller.records['api']['phase'] == 'HOLD'


def test_new_supervisor_generation_cannot_restore_old_child_proof():
    rows, launches, controller, receiver, frame = setup()
    proof=receiver.receive(frame)
    launches.retire('api')
    new_frame=launches.prepare('api',rows[123])
    launches.accept('api',answer_launch(new_frame,rows[123]))
    assert launches.status('api')['generation']==2
    with pytest.raises(ValueError,match='HOLD'):controller.accept('api',proof)
    with pytest.raises(ValueError):controller.checked('api')


@pytest.mark.parametrize('fault',['forged-proof','forged-completion','replaced-before-confirm','replayed-confirmation'])
def test_authenticated_child_failures_cannot_restore_registration(fault):
    rows, launches, controller, receiver, frame = setup()
    proof=receiver.receive(frame)
    if fault=='forged-proof':
        proof['mac']='0'*64
        with pytest.raises(ValueError,match='HOLD'):controller.accept('api',proof)
    else:
        receiver.complete(controller.accept('api',proof),lambda:True)
        if fault=='forged-completion':receiver.completion['body']['target']='0'*64
        if fault=='replaced-before-confirm':rows[os.getpid()]['created']='2026-10-14T20:00:01Z'
        if fault=='replayed-confirmation':controller.confirm('api',receiver.completion)
        with pytest.raises(ValueError,match='HOLD'):controller.confirm('api',receiver.completion)
    with pytest.raises(ValueError):controller.checked('api')


@pytest.mark.parametrize('service', tuple(MODULES))
def test_python_entry_dispatch_after_complete_handshake(monkeypatch, service):
    rows, launches, controller, receiver, frame = setup(service)
    dispatched=[]
    def application(module, **kwargs):
        assert controller.checked(service)['owner']['pid'] == os.getpid()
        assert receiver.phase == 'OBSERVED' and receiver.key is None
        assert sys.argv == [MODULES[service]]
        dispatched.append(module)
    monkeypatch.setattr('runpy.run_module',application)
    monkeypatch.setattr(sys,'argv',['fixture'])
    dispatch_python_service(receiver,frame,lambda proof:controller.accept(service,proof),
        lambda completion: bool(controller.confirm(service,completion)))
    assert dispatched == [MODULES[service]]


@pytest.mark.parametrize('service', ['web','maintain'])
def test_unsupported_language_job_entry_remains_hold(service):
    rows, launches, controller, receiver, frame = setup(service)
    with pytest.raises(ValueError,match='HOLD'):
        dispatch_python_service(receiver,frame,lambda proof:pytest.fail('No dispatch'),lambda _:True)


@pytest.mark.skipif(os.name != 'nt', reason='Windows native private-process fixture')
@pytest.mark.parametrize('service', SERVICES)
def test_private_native_child_before_dispatch(tmp_path, service):
    """Real OS process/private pipes; role-labelled synthetic work, not service readiness."""
    driver = tmp_path/'private-child.py'
    import inspect
    driver.write_text('import json,sys,os,subprocess\n' + inspect.getsource(native) + '''
from scripts.genesis_child_observation import PrivateChildReceiver
initial=json.loads(sys.stdin.buffer.readline(16385))
receiver=PrivateChildReceiver(service=sys.argv[1],launch=initial['launch'],native=native,
 ancestry=lambda child,parent:child['parent_pid']==parent['pid'] and parent['pid']==os.getppid())
proof=receiver.receive(bytes.fromhex(initial['frame']))
print(json.dumps(proof),flush=True)
reply=json.loads(sys.stdin.buffer.readline(16385))
status=receiver.complete(reply,lambda:True)
print(json.dumps(receiver.completion),flush=True)
print(json.dumps(status),flush=True)
sys.stdin.buffer.readline(2)
''')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process = subprocess.Popen([sys._base_executable, str(driver), service],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        parent = native(os.getpid()); child = native(process.pid)
        launches = LaunchObservations(native)
        launch_frame = launches.prepare(service, parent)
        launches.accept(service, answer_launch(launch_frame, parent))
        controller = ChildObservations(launches, native=native,
            ancestry=lambda c,p: c['parent_pid']==p['pid'])
        frame = controller.prepare(service, child)
        process.stdin.write(json.dumps({'launch':launches.checked(service)['challenge'],'frame':frame.hex()})+'\n')
        process.stdin.flush()
        proof = json.loads(process.stdout.readline())
        reply = controller.accept(service, proof)
        process.stdin.write(json.dumps(reply)+'\n'); process.stdin.flush()
        controller.confirm(service, json.loads(process.stdout.readline()))
        status = json.loads(process.stdout.readline())
        assert status['service'] == service and not status['write_authorized']
        assert controller.checked(service)['owner'] == child
        out, err = process.communicate('\n', timeout=10)
        assert process.returncode == 0 and not err
        assert json.loads(frame)['key'] not in out + err + json.dumps(status)
    finally:
        if process.stdin and not process.stdin.closed: process.stdin.close()
        process.wait(timeout=15)
