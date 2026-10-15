import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.genesis_background_ownership import capture
from scripts.genesis_launch_provenance import LaunchObservations, descriptor
from scripts.genesis_supervisor_observation import SupervisorObservation

ROOT = Path(__file__).resolve().parents[1]


def test_supervisor_rejects_reentry_and_heartbeat_is_not_authority(monkeypatch):
    owner = {'pid': os.getpid(), 'parent_pid': 1, 'created': '2026-10-14T20:00:00Z',
             'executable': r'C:\fixture\python.exe', 'command_sha256': 'a' * 64}
    monkeypatch.delenv('GENESIS_SUPERVISOR_LAUNCH_TOKEN', raising=False)
    registry = LaunchObservations(lambda pid: owner)
    frame = registry.prepare('entities', owner)
    replies = []
    context = SupervisorObservation(service='entities', read_private=lambda: frame,
        send_private=replies.append, native=lambda pid: owner, child=lambda *args: True)
    context.enter('entities', os.getpid())
    assert registry.accept('entities', replies[0])['phase'] == 'ATTESTED'
    heartbeat = context.heartbeat({'service': 'entities', 'supervisor_pid': os.getpid(),
                                   'supervisor_launch_token': 'SECRET_CANARY'})
    assert 'SECRET_CANARY' not in json.dumps(heartbeat)
    assert heartbeat['launch_observation']['scope'] == 'OBSERVATION_NOT_LIFECYCLE_AUTHORITY'
    with pytest.raises(ValueError): context.enter('entities', os.getpid())


@pytest.mark.parametrize('failure', ['wrong_service', 'legacy_token', 'native_replaced',
                                    'child_rejected', 'child_error', 'heartbeat_target'])
def test_supervisor_failures_latch_hold_without_secret_errors(monkeypatch, failure):
    owner = {'pid': os.getpid(), 'parent_pid': 1, 'created': '2026-10-14T20:00:00Z',
             'executable': 'fixture', 'command_sha256': 'a' * 64}
    registry = LaunchObservations(lambda pid: owner)
    frame = registry.prepare('entities', owner)
    monkeypatch.delenv('GENESIS_SUPERVISOR_LAUNCH_TOKEN', raising=False)
    def child(*args):
        if failure == 'child_error': raise RuntimeError('SECRET_CANARY')
        return False
    context = SupervisorObservation(service='entities', read_private=lambda: frame,
        send_private=lambda proof: None, native=lambda pid: owner, child=child)
    if failure == 'legacy_token': monkeypatch.setenv('GENESIS_SUPERVISOR_LAUNCH_TOKEN', 'SECRET_CANARY')
    if failure in ('wrong_service', 'legacy_token'):
        operation = lambda: context.enter('api' if failure == 'wrong_service' else 'entities', os.getpid())
    else:
        context.enter('entities', os.getpid())
        if failure == 'native_replaced': owner['created'] = '2026-10-14T20:00:01Z'
        operation = (lambda: context.child_started(None, ['fixture'])) if failure.startswith('child_') else (
            lambda: context.heartbeat({})) if failure == 'heartbeat_target' else context.verify
    with pytest.raises(ValueError) as error: operation()
    assert context.phase == 'HOLD' and 'SECRET_CANARY' not in str(error.value)


def test_uncertified_combined_supervisor_controllers_reject_before_processing(monkeypatch):
    from scripts import run_genesis_service as runner
    def forbidden(*args): pytest.fail('Conflicting controller must reject before private IO')
    context = SupervisorObservation(service='entities', read_private=forbidden,
        send_private=forbidden, native=forbidden, child=forbidden)
    monkeypatch.setattr(runner, 'LAUNCH_OBSERVATION', context)
    monkeypatch.setattr(runner, 'COOPERATIVE_SUPERVISOR', object())
    monkeypatch.setattr(sys, 'argv', ['runner', '--name', 'entities'])
    with pytest.raises(RuntimeError, match='Explicit native supervisor observer'):
        runner.main()


@pytest.mark.skipif(os.name != 'nt', reason='Native actual-runner fixture required')
@pytest.mark.parametrize('venv_wrapper,private_bootstrap', [(False,False),(True,False),(False,True)])
def test_actual_runner_main_private_launch_child_and_redacted_heartbeat(tmp_path, venv_wrapper, private_bootstrap):
    root = tmp_path / 'isolated-repository'; scripts = root / 'scripts'; scripts.mkdir(parents=True)
    for name in ('run_genesis_service.py', 'genesis_runtime.py'):
        source = Path(os.environ['GENESIS_TEST_RUNNER_SOURCE']) if name == 'run_genesis_service.py' and os.environ.get('GENESIS_TEST_RUNNER_SOURCE') else ROOT / 'scripts' / name
        shutil.copyfile(source, scripts / name)
    (root / 'docker-compose.yml').write_text('services: {}')
    if venv_wrapper:
        subprocess.run([sys._base_executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True, timeout=30)
    module = root / 'services/entity-resolver/src/entity_resolver'; module.mkdir(parents=True)
    (module / '__init__.py').write_text('')
    finish = root / 'finish'
    (module / 'cli.py').write_text('import os,time,pathlib\np=pathlib.Path(os.environ["STINKY_ROOT"])/"finish"\n'
                                 'while not p.exists():time.sleep(.05)\n')
    driver = root / 'driver.py'
    driver.write_text('''import sys,os,json,importlib.util,threading,ntpath
from pathlib import Path
from scripts.genesis_background_ownership import capture
from scripts.genesis_launch_provenance import descriptor
from scripts.genesis_supervisor_observation import SupervisorObservation
root=Path(sys.argv[1]);private_bootstrap=sys.argv[2]=='private';sys.argv=[str(root/'scripts/run_genesis_service.py'),'--name','entities']
spec=importlib.util.spec_from_file_location('isolated_runner',root/'scripts/run_genesis_service.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
frame=bytes.fromhex(json.loads(sys.stdin.readline())['frame'])
def native(pid):
 if private_bootstrap:
  from scripts.genesis_private_child_entry import native as private_native
  return private_native(pid)
 data=capture();a=next(r for r in data['before'] if r['pid']==pid);b=next(r for r in data['after'] if r['pid']==pid)
 if descriptor(a)!=descriptor(b):raise ValueError('Native identity changed')
 return descriptor(b)
done=threading.Event()
def child(proc,command,owner):
 data=capture();a=next(r for r in data['before'] if r['pid']==proc.pid);b=next(r for r in data['after'] if r['pid']==proc.pid)
 if descriptor(a)!=descriptor(b) or b['parent_pid']!=owner['pid']:return False
 if b['argv'][1:]!=list(command[1:]):return False
 nodes={r['pid']:r for r in data['after']};members={proc.pid}
 for _ in range(8):
  added={p for p,r in nodes.items() if r['parent_pid'] in members}-members
  if not added:break
  members.update(added)
 for member in members:
  row=nodes[member]
  old=next(r for r in data['before'] if r['pid']==member)
  if descriptor(old)!=descriptor(row):return False
  if row['argv'][1:]!=list(command[1:]):
   expected=ntpath.normcase(ntpath.join(os.environ['SystemRoot'],'System32','conhost.exe'))
   if not (ntpath.normcase(row['executable'])==expected and row['argv'][1:]==['0x4']):
    (root/'child-disagreement.json').write_text(json.dumps({'pid':member,'executable':row['executable'],'argc':len(row['argv'])}))
    return False
 (root/'child-proof.json').write_text(json.dumps({'pid':proc.pid,'parent_pid':b['parent_pid'],'creation':b['created'],'members':sorted(members)}))
 def complete():proc.wait(timeout=20);done.set()
 threading.Thread(target=complete,daemon=True).start()
 (root/'finish').write_text('isolated fixture may finish')
 return True
channel=None
if private_bootstrap:
 from scripts.genesis_child_observation import ChildObservations
 from scripts.genesis_private_child_channel import PrivatePythonChildChannel
 private=json.loads(frame)
 class LaunchView:
  def checked(self,service):
   if service!='entities' or native(private['challenge']['owner']['pid'])!=private['challenge']['owner']:
    raise ValueError('Fixture supervisor generation replaced')
   return {'challenge':private['challenge'],'key':bytes.fromhex(private['key'])}
 children=ChildObservations(LaunchView(),native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
 channel=PrivatePythonChildChannel(service='entities',controller=children,native=native)
runner.LAUNCH_OBSERVATION=SupervisorObservation(service='entities',read_private=lambda:frame,
 send_private=lambda proof:print(json.dumps(proof),flush=True),native=native,child=child,private_child=channel)
# Bound only the fixture's repeated workload; this is not shutdown certification.
runner.supervisor_running=lambda:not done.is_set()
runner.API_HEALTH_POLL_SECONDS=.05
try:result=runner.main()
except Exception as error:
 import traceback
 (root/'failure.json').write_text(json.dumps({'type':type(error).__name__,'channel':channel.phase if channel else None,'stage':channel.failure_stage if channel else None,'frames':[{'function':r.name,'line':r.lineno} for r in traceback.extract_tb(error.__traceback__)]}))
 raise
raise SystemExit(result)
''')
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop('GENESIS_SUPERVISOR_LAUNCH_TOKEN', None)
    proc = subprocess.Popen([sys._base_executable, str(driver), str(root), 'private' if private_bootstrap else 'legacy'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        def native(pid):
            data = capture(); a = next(r for r in data['before'] if r['pid'] == pid)
            b = next(r for r in data['after'] if r['pid'] == pid)
            assert descriptor(a) == descriptor(b)
            return descriptor(b)
        registry = LaunchObservations(native)
        frame = registry.prepare('entities', native(proc.pid))
        proc.stdin.write(json.dumps({'frame': frame.hex()}) + '\n'); proc.stdin.flush()
        assert registry.accept('entities', json.loads(proc.stdout.readline()))['phase'] == 'ATTESTED'
        stdout, stderr = proc.communicate(timeout=60 if private_bootstrap else 35)
        assert proc.returncode == 0, 'Isolated real runner did not finish normally'
        heartbeat = json.loads((root / 'logs/runtime-state-entities.json').read_text())
        assert heartbeat['supervisor_pid'] == proc.pid
        assert heartbeat['launch_observation']['generation'] == 1
        assert 'supervisor_launch_token' not in heartbeat
        assert (root / 'child-proof.json').exists()
        proof = json.loads((root / 'child-proof.json').read_text())
        assert len(proof['members']) >= (2 if venv_wrapper else 1)
        secret = json.loads(frame)['key']
        leaked = any(secret in value for value in (stdout, stderr, json.dumps(heartbeat),
                     (root / 'logs/entities.log').read_text()))
        assert not leaked
    finally:
        finish.write_text('fixture cleanup')
        if proc.stdin and not proc.stdin.closed: proc.stdin.close()
        proc.wait(timeout=15)
