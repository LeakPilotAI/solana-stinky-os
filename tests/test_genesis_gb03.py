import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.genesis_launch_provenance import LaunchObservations,answer_launch,descriptor
from scripts.genesis_child_observation import ChildObservations
from scripts.genesis_private_child_entry import native
from scripts.genesis_private_child_channel import PrivatePythonChildChannel
from scripts.genesis_wrapper_observation import WrapperObservation
from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS

ROOT=Path(__file__).resolve().parents[1]


def launch(service):
    owner=native(os.getpid());registry=LaunchObservations(native)
    frame=registry.prepare(service,owner);registry.accept(service,answer_launch(frame,owner))
    return owner,registry


def test_wrapper_exact_policy_and_failure_matrix():
    command=[r'C:\venv\Scripts\python.exe','-m','fixture']
    parent={'pid':1,'parent_pid':0,'created':'2026-10-15T01:00:00Z','executable':'parent','command_sha256':'a'*64}
    root=dict(parent,pid=2,parent_pid=1,executable=command[0],argv=command)
    leaf=dict(root,pid=3,parent_pid=2,executable=r'C:\Python\python.exe')
    def check(change=None):
        rows={1:dict(parent),2:dict(root),3:dict(leaf)}
        if change:change(rows)
        census=lambda:{'before':list(rows.values()),'after':list(rows.values())}
        policy=WrapperObservation(native=lambda pid:rows[pid],census=census,
            executables=(command[0],leaf['executable']))
        policy.bind(2,3,command,parent)
        return policy,rows
    policy,rows=check();assert len(policy.rows)==2 and not policy.audit()['lifecycle_authorized']
    for mutation in [lambda r:r[3].update(executable=r'C:\foreign\python.exe'),
                     lambda r:r[3].update(argv=[command[0],'-m','foreign']),
                     lambda r:r[3].update(parent_pid=99),
                     lambda r:r.update({4:dict(leaf,pid=4,parent_pid=3)})]:
        with pytest.raises((ValueError,KeyError)):check(mutation)
    rows[3]['created']='2026-10-15T01:00:01Z'
    with pytest.raises(ValueError):policy.verify()
    policy,rows=check();rows[3]['argv']=[command[0],'-m','forged']
    with pytest.raises(ValueError):policy.audit()


@pytest.mark.parametrize('fault',[None,'pid-reuse','duplicate','missing','foreign'])
def test_native_batch_requires_complete_stable_phase(monkeypatch,fault):
    from types import SimpleNamespace
    from scripts import genesis_private_child_entry as entry
    monkeypatch.setattr(entry,'os',SimpleNamespace(name='nt'))
    first={'pid':123,'parent_pid':1,'created':'2026-10-15T01:00:00Z','executable':'fixture','command':'one'}
    second=dict(first,pid=124,command='two')
    rows=[dict(first),dict(second),dict(first),dict(second)]
    if fault=='pid-reuse':rows[-1]['created']='2026-10-15T01:00:01Z'
    if fault=='duplicate':rows[-1]['pid']=123
    if fault=='missing':rows.pop()
    if fault=='foreign':rows[-1]['pid']=125
    monkeypatch.setattr(entry.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(rows).encode()))
    if fault:
        with pytest.raises(ValueError):entry.native_many((123,124))
    else:
        observed=entry.native_many((123,124));assert set(observed)=={123,124}
        assert observed[123]['command_sha256']!=observed[124]['command_sha256']


@pytest.mark.skipif(os.name!='nt',reason='Native Windows venv wrapper fixture')
def test_native_venv_wrapper_private_handshake(tmp_path):
    from scripts.genesis_background_ownership import capture
    venv=tmp_path/'venv'
    subprocess.run([sys._base_executable,'-m','venv','--without-pip',str(venv)],check=True,timeout=30)
    module=tmp_path/'entity_resolver';module.mkdir();(module/'__init__.py').write_text('')
    (module/'cli.py').write_text("import sys\nprint('VENV_AUTHENTICATED',flush=True)\nsys.stdin.readline()\n")
    py=str(venv/'Scripts/python.exe');owner,launches=launch('entities')
    children=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
    wrapper=WrapperObservation(native=native,census=capture,executables=(py,sys._base_executable))
    channel=PrivatePythonChildChannel(service='entities',controller=children,native=native,wrapper=wrapper)
    command=channel.command_for([py,'-m','entity_resolver.cli'])
    env=dict(os.environ,PYTHONPATH=str(tmp_path)+os.pathsep+str(ROOT))
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=tmp_path)
    try:
        try: result=channel.deliver(proc,command,owner)
        except ValueError:
            (tmp_path/'diagnostic.json').write_text(json.dumps({'stage':channel.failure_stage,'phase':channel.phase,'exit':proc.poll()}))
            raise
        assert result
        assert proc.stdout.readline().strip()=='VENV_AUTHENTICATED'
        assert len(wrapper.rows)==2 and children.checked('entities')['owner']['pid']!=proc.pid
        out,err=proc.communicate('\n',timeout=15);assert proc.returncode==0 and not err
    finally:
        if proc.stdin and not proc.stdin.closed:proc.stdin.close()
        proc.wait(timeout=15)


@pytest.mark.skipif(os.name!='nt',reason='Native Node/private stdin fixture')
@pytest.mark.parametrize('unexpected_descendant',[False,True])
def test_native_node_socket_and_cp77_stdin_preservation(tmp_path,unexpected_descendant):
    from scripts.genesis_node_observation import PrivateNodeChildChannel
    from scripts.genesis_background_ownership import capture,listener_identity
    node=shutil.which('node');assert node
    script=tmp_path/'isolated-server.cjs'
    script.write_text(("const child=require('node:child_process').spawn(process.execPath,['-e','process.stdin.resume()'],{stdio:['pipe','ignore','ignore']});" if unexpected_descendant else "const child=null;")+
        "const http=require('node:http');const s=http.createServer((q,r)=>r.end('isolated'));"
        "s.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:s.address().port})));"
        "let raw='';process.stdin.on('data',b=>{raw+=b;if(raw.includes('\\n')){if(child)child.stdin.end();console.log('STDIN_PRESERVED');s.close(()=>process.exitCode=0);process.stdin.destroy();}});"
        "process.stdin.on('end',()=>{if(child)child.stdin.end();s.close();});")
    owner,launches=launch('web');children=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
    channel=PrivateNodeChildChannel(command=(node,str(script)),controller=children,native=native)
    command=channel.command_for([node,str(script)])
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=tmp_path)
    try:
        try: result=channel.deliver(proc,command,owner)
        except ValueError:
            (tmp_path/'diagnostic.json').write_text(json.dumps({'stage':channel.failure_stage,'phase':channel.phase,'exit':proc.poll()}))
            raise
        assert result
        port=json.loads(proc.stdout.readline())['port']
        assert listener_identity(capture((port,)),proc.pid,port)
        if unexpected_descendant:
            policy=WrapperObservation(native=native,census=capture,executables=(node,))
            with pytest.raises(ValueError,match='descendants'):policy.bind(proc.pid,proc.pid,command,owner)
        import urllib.request
        assert urllib.request.urlopen(f'http://127.0.0.1:{port}',timeout=3).read()==b'isolated'
        out,err=proc.communicate('CP77_TEST_FRAME\n',timeout=15)
        assert 'STDIN_PRESERVED' in out and proc.returncode==0 and not err
    finally:
        if proc.stdin and not proc.stdin.closed:proc.stdin.close()
        proc.wait(timeout=15)


@pytest.mark.parametrize('loop',sorted(LOOPS))
@pytest.mark.skipif(os.name!='nt',reason='Native maintenance private entry')
def test_native_maintenance_loop_job(tmp_path,loop):
    script=tmp_path/'job.py';script.write_text("import sys\nprint('MAINTENANCE_AUTHENTICATED',flush=True)\nsys.stdin.readline()\n")
    command=(sys._base_executable,str(script));owner,launches=launch('maintain')
    manager=MaintenanceObservation(launches=launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest={name:[(command,script)] for name in LOOPS})
    with manager.loop(loop),manager.job(command) as channel:
        wrapped=channel.command_for(command)
        proc=subprocess.Popen(wrapped,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            env=dict(os.environ,PYTHONPATH=str(ROOT)),cwd=tmp_path)
        try:
            try: result=channel.deliver(proc,wrapped,owner)
            except ValueError:
                (tmp_path/'diagnostic.json').write_text(json.dumps({'stage':channel.failure_stage,'phase':channel.phase,'exit':proc.poll()}))
                raise
            assert result
            assert proc.stdout.readline().strip()=='MAINTENANCE_AUTHENTICATED'
            out,err=proc.communicate('\n',timeout=15);assert proc.returncode==0 and not err
        finally:
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
            proc.wait(timeout=15)
    assert manager.phase=='READY'


@pytest.mark.skipif(os.name!='nt',reason='Native short-lived venv maintenance job')
def test_short_venv_job_does_not_race_final_audit(tmp_path):
    from scripts.genesis_background_ownership import capture
    py=str(ROOT/'.venv/Scripts/python.exe')
    source=tmp_path/'quick.py';source.write_text("print('QUICK_JOB_COMPLETED',flush=True)\n")
    command=(py,str(source));owner,launches=launch('maintain')
    manager=MaintenanceObservation(launches=launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest={name:[(command,source)] for name in LOOPS},
        wrapper_factory=lambda:WrapperObservation(native=native,census=capture,executables=(py,sys._base_executable)))
    with manager.loop('v2-maintenance'),manager.job(command) as channel:
        wrapped=channel.command_for(command)
        proc=subprocess.Popen(wrapped,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            env=dict(os.environ,PYTHONPATH=str(ROOT)),cwd=tmp_path)
        try:
            try:result=channel.deliver(proc,wrapped,owner)
            except ValueError:
                (tmp_path/'quick-diagnostic.json').write_text(json.dumps({'stage':channel.failure_stage,'exit':proc.poll()}))
                raise
            assert result
            out,err=proc.communicate(timeout=15)
            assert 'QUICK_JOB_COMPLETED' in out and proc.returncode==0 and not err
        finally:
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
            proc.wait(timeout=15)


@pytest.mark.skipif(os.name!='nt',reason='Native frozen-worker CLI-only bootstrap')
def test_frozen_v2_cli_help_bootstrap_without_database(tmp_path):
    import hashlib
    from scripts.genesis_background_ownership import capture
    source=ROOT/'scripts/run_intelligence_execution_v2.py'
    before=source.read_bytes()
    committed=subprocess.check_output(['git','show','HEAD:scripts/run_intelligence_execution_v2.py'],cwd=ROOT)
    assert committed.decode().replace('\r\n','\n')==source.read_text()
    py=str(ROOT/'.venv/Scripts/python.exe');command=(py,str(source),'--help')
    owner,launches=launch('maintain')
    manager=MaintenanceObservation(launches=launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest={loop:[(command,source)] for loop in LOOPS},
        wrapper_factory=lambda:WrapperObservation(native=native,census=capture,executables=(py,sys._base_executable)))
    with manager.loop('v2-maintenance'),manager.job(command) as channel:
        wrapped=channel.command_for(command)
        env=dict(os.environ,PYTHONPATH=str(ROOT),STINKY_DATABASE_URL='invalid://NO_DATABASE_ALLOWED')
        proc=subprocess.Popen(wrapped,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=tmp_path)
        try:
            assert channel.deliver(proc,wrapped,owner)
            out,err=proc.communicate(timeout=15)
            assert proc.returncode==0 and 'usage:' in out and '--report' in out and not err
        finally:
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
            proc.wait(timeout=15)
    assert source.read_bytes()==before and manager.phase=='READY'


@pytest.mark.parametrize('fault',['no-loop','wrong-loop','changed-source','duplicate-loop','unresolved'])
def test_maintenance_holds_unknown_or_uncertain_work(tmp_path,fault):
    from tests.test_genesis_child_observation import setup
    rows,launches,children,receiver,frame=setup('maintain')
    source=tmp_path/'job.py';source.write_text('pass')
    command=(sys._base_executable,str(source))
    manager=MaintenanceObservation(launches=launches,native=lambda pid:rows[pid],ancestry=lambda c,p:True,
        manifest={name:[(command,source)] for name in LOOPS})
    if fault=='no-loop':
        with pytest.raises(ValueError):
            with manager.job(command):pytest.fail('Unregistered loop')
        return
    with manager.loop('v2-maintenance'):
        if fault=='duplicate-loop':
            with pytest.raises(ValueError):
                with manager.loop('v2-maintenance'):pytest.fail('Duplicate loop')
            return
        if fault=='changed-source':source.write_text('changed')
        if fault=='wrong-loop':command=(sys._base_executable,'unknown.py')
        with pytest.raises(ValueError):
            with manager.job(command):pass
    if fault in ('changed-source','unresolved'):assert manager.phase=='HOLD'


def test_actual_runner_three_loop_admission_is_thread_local(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from scripts import run_genesis_service as runner
    from scripts.genesis_supervisor_observation import SupervisorObservation
    source=tmp_path/'job.py';source.write_text('pass')
    command=(sys._base_executable,str(source))
    owner={'pid':os.getpid(),'parent_pid':1,'created':'2026-10-15T01:00:00Z','executable':'fixture','command_sha256':'a'*64}
    launches=LaunchObservations(lambda pid:owner);frame=launches.prepare('maintain',owner)
    manager=MaintenanceObservation(launches=launches,native=lambda pid:owner,ancestry=lambda c,p:True,
        manifest={loop:[(command,source)] for loop in LOOPS})
    observer=SupervisorObservation(service='maintain',read_private=lambda:frame,
        send_private=lambda proof:launches.accept('maintain',proof),native=lambda pid:owner,
        child=lambda *a:True,maintenance=manager)
    # The controller's private registry must already attest the exact generation.
    launches.accept('maintain',answer_launch(frame,owner))
    observer._send=lambda proof:None
    observer.enter('maintain',os.getpid())
    monkeypatch.setattr(runner,'LAUNCH_OBSERVATION',observer)
    barrier=threading.Barrier(3)
    class Completed:
        def poll(self):return 0
    def exercise(loop):
        @runner.supervisor_loop(loop)
        def operation():
            with observer.job(command) as channel:
                wrapped=observer.child_command(command)
                assert wrapped[3:5]==['maintain','--job'] and observer.private_pipe
                assert channel.work['loop']==loop
                barrier.wait(timeout=5)
                channel.process=Completed();channel.phase='OBSERVED'
                return channel.work['job_id']
        return operation()
    with ThreadPoolExecutor(3) as pool:ids=list(pool.map(exercise,sorted(LOOPS)))
    assert len(set(ids))==3 and not manager.active and manager.count==3


@pytest.mark.parametrize('fault',['forged-proof','bad-receipt','duplicate-proof','timeout','final-audit'])
@pytest.mark.skipif(os.name!='nt',reason='Native Node authentication rejection')
def test_native_node_rejects_without_dispatch(tmp_path,fault,monkeypatch):
    from scripts.genesis_node_observation import PrivateNodeChildChannel
    node=shutil.which('node');assert node
    marker=tmp_path/'unauthorized'
    script=tmp_path/'denied.cjs';script.write_text("require('node:fs').writeFileSync("+json.dumps(str(marker)) +",'bad')")
    owner,launches=launch('web');children=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
    original=children.accept
    def accept(service,proof):
        if fault=='forged-proof':proof['mac']='0'*64
        reply=original(service,proof)
        if fault=='duplicate-proof':return original(service,proof)
        if fault=='bad-receipt':reply['body']['target']='0'*64
        return reply
    monkeypatch.setattr(children,'accept',accept)
    wrapper=None
    if fault=='final-audit':
        from scripts.genesis_background_ownership import capture
        wrapper=WrapperObservation(native=native,census=capture,executables=(node,))
        original_audit=wrapper.audit;calls=[]
        def audit():
            calls.append(True)
            if len(calls)==2:raise ValueError('Injected final tree mismatch')
            return original_audit()
        monkeypatch.setattr(wrapper,'audit',audit)
    channel=PrivateNodeChildChannel(command=(node,str(script)),controller=children,native=native,
        timeout=.02 if fault=='timeout' else 30,wrapper=wrapper)
    command=channel.command_for([node,str(script)])
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=tmp_path)
    try:
        with pytest.raises(ValueError,match='HOLD'):channel.deliver(proc,command,owner)
        assert channel.phase=='HOLD' and not marker.exists()
    finally:
        if proc.stdin and not proc.stdin.closed:proc.stdin.close()
        proc.wait(timeout=15)
    assert not marker.exists()


def test_actual_next_production_private_bootstrap_cp77_join(tmp_path,monkeypatch):
    """Supplemental working-tree CP77 proof, explicitly separate from clean-code certification."""
    if os.environ.get('GENESIS_GB03_NEXT_NATIVE')!='isolated-gb03':
        pytest.skip('Explicit existing CP77/Next isolated fixture required')
    from tests.genesis_native_production_web import ProductionWebFixture
    from scripts.genesis_node_observation import PrivateNodeChildChannel
    owner,launches=launch('web')
    children=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'])
    fixture=ProductionWebFixture(tmp_path/'real-next')
    original=subprocess.Popen;channels=[]
    def spawn(command,**options):
        assert len(command)==2 and Path(command[1]).resolve()==ROOT/'scripts/genesis_web_lifecycle.cjs'
        node=shutil.which(command[0]);assert node
        channel=PrivateNodeChildChannel(command=(node,command[1]),controller=children,native=native)
        wrapped=channel.command_for([node,command[1]])
        monkeypatch.setattr(subprocess,'Popen',original)
        process=original(wrapped,**options)
        try:channel.deliver(process,wrapped,owner)
        except Exception:
            process.stdin.close();process.wait(timeout=15)
            raise
        channels.append(channel);return process
    monkeypatch.setattr(subprocess,'Popen',spawn)
    try:
        fixture.start();assert channels[0].phase=='OBSERVED'
        from scripts.genesis_background_ownership import capture,listener_identity
        assert listener_identity(capture((fixture.port,)),fixture.process.pid,fixture.port)
        fixture.begin_request();fixture.request_stop()
        proof=fixture.verify_exit();assert proof['active_processes']==0
    finally:
        monkeypatch.setattr(subprocess,'Popen',original)
        if getattr(fixture,'job',None) is not None:fixture.preserve()
