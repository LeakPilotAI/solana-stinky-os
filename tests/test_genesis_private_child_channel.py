import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.genesis_background_ownership import MODULES
from scripts.genesis_launch_provenance import LaunchObservations, answer_launch
from scripts.genesis_child_observation import ChildObservations
from scripts.genesis_private_child_channel import PrivatePythonChildChannel
from tests.test_genesis_child_observation import native, setup


@pytest.mark.parametrize('service', tuple(MODULES))
@pytest.mark.skipif(os.name!='nt',reason='Actual Windows private child entry')
def test_actual_python_entry_gates_isolated_workload(tmp_path,service):
    module=tmp_path/MODULES[service].split('.')[0]; module.mkdir()
    (module/'__init__.py').write_text('')
    (module/'cli.py').write_text("import sys\nprint('ISOLATED_APPLICATION_DISPATCHED',flush=True)\nsys.stdin.readline()\n")
    owner=native(os.getpid()); launches=LaunchObservations(native)
    frame=launches.prepare(service,owner);launches.accept(service,answer_launch(frame,owner))
    children=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
    channel=PrivatePythonChildChannel(service=service,controller=children,native=native)
    command=channel.command_for([sys._base_executable,'-m',MODULES[service]])
    env=dict(os.environ,PYTHONPATH=str(tmp_path)+os.pathsep+str(Path(__file__).resolve().parents[1]))
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,env=env,cwd=tmp_path)
    try:
        assert channel.deliver(process,command,owner)
        assert process.stdout.readline().strip()=='ISOLATED_APPLICATION_DISPATCHED'
        assert channel.phase=='OBSERVED' and children.checked(service)['owner']['pid']==process.pid
        stdout,stderr=process.communicate('\n',timeout=15)
        assert process.returncode==0 and not stderr
        assert not stdout
    finally:
        if process.stdin and not process.stdin.closed: process.stdin.close()
        process.wait(timeout=20)


@pytest.mark.parametrize('command', [['python','-c','bad'],['python','-m','event_log.cli'],
                                    ['python','-m','stinky_api.cli','extra']])
def test_channel_rejects_unrelated_command_before_spawn(command):
    rows,launches,children,receiver,frame=setup()
    channel=PrivatePythonChildChannel(service='api',controller=children,native=lambda pid:rows[pid])
    with pytest.raises(ValueError,match='HOLD'):channel.command_for(command)
    assert channel.phase=='HOLD'


def test_child_channel_cannot_be_reused():
    rows,launches,children,receiver,frame=setup()
    channel=PrivatePythonChildChannel(service='api',controller=children,native=lambda pid:rows[pid])
    channel.command_for(['python','-m','stinky_api.cli'])
    with pytest.raises(ValueError,match='HOLD'):channel.command_for(['python','-m','stinky_api.cli'])


@pytest.mark.parametrize('fault',['ready','missing-pipe','timeout'])
def test_bad_or_stalled_channel_holds_without_termination(fault):
    import io
    import time
    rows,launches,children,receiver,frame=setup()
    class Slow:
        def readline(self,bound):time.sleep(.1);return ''
    class Process:
        pid=os.getpid()
        stdin=None if fault=='missing-pipe' else io.StringIO()
        stdout=Slow() if fault=='timeout' else io.StringIO('{}\n')
        def poll(self):return None
        def terminate(self):pytest.fail('Observation cannot authorize termination')
    channel=PrivatePythonChildChannel(service='api',controller=children,native=lambda pid:rows[pid],timeout=.03)
    command=channel.command_for(['python','-m','stinky_api.cli'])
    with pytest.raises(ValueError,match='HOLD'):channel.deliver(Process(),command,rows[123])
    time.sleep(.15)
    assert channel.phase=='HOLD' and children.records['api']['phase']=='HOLD'


@pytest.mark.parametrize('fault',[None,'forged-ready','lost-ready'])
def test_channel_requires_final_processed_receipt(fault):
    import json
    from scripts.genesis_child_observation import PrivateChildReceiver,target
    from scripts.genesis_launch_provenance import encoded,signed,authenticated
    rows,launches,children,_,_=setup()
    children.records.clear()  # Fresh isolated controller, no live registrations.
    messages=[json.dumps({'kind':'genesis-private-child-ready-v1','pid':os.getpid()})+'\n']
    receiver=None;key=None;writes=[]
    class Pipe:
        def readline(self,bound):return messages.pop(0) if messages else ''
        def write(self,raw):
            nonlocal receiver,key
            body=json.loads(raw);writes.append(body)
            if len(writes)==1:
                frame=bytes.fromhex(body['frame']);key=bytes.fromhex(json.loads(frame)['key'])
                receiver=PrivateChildReceiver(service='api',launch=body['launch'],
                    native=lambda pid:rows[pid],ancestry=lambda c,p:c['parent_pid']==p['pid'])
                messages.append(json.dumps(receiver.receive(frame))+'\n')
            elif len(writes)==2:
                receiver.complete(body,lambda:True)
                messages.append(json.dumps(receiver.completion)+'\n')
            else:
                assert authenticated(key,body)['target']==target(receiver.completion)
                if fault!='lost-ready':
                    reply=signed(key,{'kind':'genesis-child-dispatch-ready-v1',
                        'target':'0'*64 if fault else target(receiver.completion)})
                    messages.append(json.dumps(reply)+'\n')
        def flush(self):pass
    pipe=Pipe()
    class Process:
        pid=os.getpid();stdin=pipe;stdout=pipe
        def poll(self):return None
    channel=PrivatePythonChildChannel(service='api',controller=children,native=lambda pid:rows[pid])
    command=channel.command_for(['python','-m','stinky_api.cli'])
    if fault:
        with pytest.raises(ValueError,match='HOLD'):channel.deliver(Process(),command,rows[123])
        assert channel.phase=='HOLD' and children.records['api']['phase']=='HOLD'
        assert channel.failure_stage=='DISPATCH_READY'
    else:
        assert channel.deliver(Process(),command,rows[123])
        assert channel.phase=='OBSERVED' and len(writes)==3


@pytest.mark.parametrize('fault',['pid-reuse','missing','wrong-pid','empty-command','oversize','exit'])
def test_exact_native_bracket_rejects_incomplete_or_replaced_identity(monkeypatch,fault):
    import json
    from types import SimpleNamespace
    from scripts import genesis_private_child_entry as entry
    row={'pid':123,'parent_pid':1,'created':'2026-10-15T01:00:00Z',
         'executable':'fixture-python','command':'fixture-child'}
    rows=[dict(row),dict(row)]
    if fault=='pid-reuse':rows[1]['created']='2026-10-15T01:00:01Z'
    if fault=='missing':rows=[]
    if fault=='wrong-pid':rows[1]['pid']=124
    if fault=='empty-command':rows[1]['command']=''
    stdout=b'x'*131073 if fault=='oversize' else json.dumps(rows).encode()
    result=SimpleNamespace(returncode=1 if fault=='exit' else 0,stdout=stdout)
    monkeypatch.setattr(entry.subprocess,'run',lambda *a,**kw:result)
    with pytest.raises(ValueError):entry.native(123)
