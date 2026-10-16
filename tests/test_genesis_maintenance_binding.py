import hashlib
import ast
import __future__
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts import run_genesis_service as runner
from scripts.genesis_launch_provenance import LaunchObservations, answer_launch
from scripts.genesis_maintenance_observation import MaintenanceObservation, LOOPS
from scripts.genesis_maintenance_binding import MaintenanceBinding
from scripts.genesis_supervisor_admission import SupervisorAdmission, FencedAdmission
from scripts.genesis_supervisor_observation import SupervisorObservation

ROOT=Path(__file__).resolve().parents[1]


def ticks(pid):
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];k.CloseHandle.argtypes=[wintypes.HANDLE]
    h=k.OpenProcess(0x1000,False,pid)
    if not h:raise RuntimeError('Native process unavailable')
    try:
        ts=[wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h,*[ctypes.byref(t) for t in ts]):raise RuntimeError('Native creation unavailable')
        return ts[0].dwLowDateTime+(ts[0].dwHighDateTime<<32)
    finally:k.CloseHandle(h)


def build(tmp_path, native=False):
    owner={'pid':os.getpid(),'parent_pid':1,'created':'2026-10-15T01:00:00Z','executable':'fixture','command_sha256':'a'*64}
    nativefn=lambda pid:dict(owner)
    if native:
        from scripts.genesis_private_child_entry import native as nativefn
        owner=nativefn(os.getpid())
    launch=LaunchObservations(nativefn);frame=launch.prepare('maintain',owner)
    launch.accept('maintain',answer_launch(frame,owner))
    src=tmp_path/'job.py';src.write_text('pass');command=(sys._base_executable,str(src))
    def retired(p,w):return {'root_pid':p.pid,'root_exit_code':0,'active_descendants':0,'identity_verified':True,'job_id':w['job_id'],'source_sha256':w['sha256']}
    m=MaintenanceObservation(launches=launch,native=nativefn,ancestry=lambda c,p:True,
        manifest={n:[(command,src)] for n in LOOPS},retirement=retired)
    observer=SupervisorObservation(service='maintain',read_private=lambda:frame,send_private=lambda p:None,
        native=nativefn,child=lambda *args:True,maintenance=m)
    dt=datetime.fromisoformat(owner['created'].replace('Z','+00:00'))-datetime(1970,1,1,tzinfo=timezone.utc)
    created=(dt.days*86400+dt.seconds)*10000000+dt.microseconds*10+116444736000000000
    if native:created=ticks(os.getpid())
    gowner={'pid':os.getpid(),'creation_ticks':created,'service':'maintain','command_sha256':owner['command_sha256'],
        'repository_sha256':hashlib.sha256(str(ROOT).encode()).hexdigest()}
    def gate_native():
        if native:
            row=nativefn(os.getpid())
            return {**gowner,'pid':row['pid'],'creation_ticks':ticks(os.getpid()),'command_sha256':row['command_sha256']}
        return dict(gowner)
    gate=SupervisorAdmission(gowner,generation=1,verify_native=gate_native,persist=lambda p:hashlib.sha256(repr(p).encode()).hexdigest())
    binding=MaintenanceBinding(observer,gate,repository=ROOT,isolated=True,
        idle=lambda:{'active_descendants':0,'unresolved_writers':0,'identity_verified':True})
    return binding,observer,gate,m,launch,command


def install(monkeypatch,parts,entered=True):
    b,o,g,*_=parts
    monkeypatch.setattr(runner,'LAUNCH_OBSERVATION',o);monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',g)
    monkeypatch.setattr(runner,'MAINTENANCE_BINDING',None)
    runner.install_maintenance_binding(b)
    if entered:o.enter('maintain',os.getpid())


def exercise(parts):
    b,o,g,m,launch,cmd=parts;ready=threading.Barrier(4);errors=[];threads=[];effects=[]
    def worker(loop):
        @runner.supervisor_loop(loop)
        def body():
            ready.wait(timeout=10)
            while runner.supervisor_running():
                try:runner.run_admitted_job(['synthetic-watchdog-or-file'],lambda:effects.append(loop))
                except FencedAdmission:
                    if runner.supervisor_running():raise
                runner.supervisor_wait(.001)
        try:body()
        except Exception as e:errors.append(type(e).__name__)
    for loop in sorted(LOOPS):
        t=threading.Thread(target=worker,args=(loop,));t.start();threads.append(t)
    try:
        ready.wait(timeout=10)
        ack=g.quiesce({'request_id':'a'*32,'manifest_sha256':g.manifest()},timeout=10)
        for t in threads:t.join(5)
        assert not errors and all(not t.is_alive() for t in threads)
        proof=b.verify_drained()
        assert not runner.supervisor_running() and not g.jobs and not m.active
        with pytest.raises(FencedAdmission):runner.run_admitted_job(['new'],lambda:effects.append('BAD'))
        assert 'BAD' not in effects
        return {'phase':ack['phase'],'loops':sorted(g.loops),'proof':proof,'threads_exited':True}
    finally:
        g.stop_event.set()  # Cooperative fixture-only cleanup; no process signal.
        for t in threads:t.join(5)


def test_integrated_three_real_runner_loop_helpers_drain(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts)
    assert exercise(parts)['phase']=='QUIESCED'


def test_combined_main_preflight_and_actual_ownership_file_ticket(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts,entered=False);b,o,g,*_=parts
    fixture=tmp_path/'root';(fixture/'scripts').mkdir(parents=True);(fixture/'docker-compose.yml').write_text('services: {}')
    monkeypatch.setattr(runner,'__file__',str(fixture/'scripts/run_genesis_service.py'))
    monkeypatch.setattr(runner,'restore_search_path',lambda:None);monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys,'argv',['isolated','--name','maintain'])
    class EndProbe(RuntimeError):pass
    def write(path,payload):
        assert g.jobs and o.phase=='OBSERVED'
        assert path.parent==fixture/'logs'
        raise EndProbe('Certified pre-loop boundary; do not start actual jobs')
    monkeypatch.setattr(runner,'write_state',write)
    with pytest.raises(EndProbe):runner.main()
    assert not g.jobs


def test_admitted_watchdog_file_work_completes_after_fence(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts);b,o,g,m,*_=parts
    effects=[]
    with runner.supervisor_job(['watchdog']):
        g.phase='DRAINING';g.stop_event.set()
        runner.run_admitted_job(['file'],lambda:effects.append('completed'))
    assert effects==['completed'] and not g.jobs
    with pytest.raises(FencedAdmission):runner.run_admitted_job(['file'],lambda:effects.append('BAD'))


@pytest.mark.parametrize('fault',['generation','pid','creation','command','repository','signature','idle','alternate-manager','direct-job'])
def test_binding_rejects_uncertain_or_unregistered_work(tmp_path,monkeypatch,fault):
    parts=build(tmp_path);install(monkeypatch,parts);b,o,g,m,launch,cmd=parts
    if fault=='generation':g.generation=2
    elif fault=='pid':g.owner['pid']+=1
    elif fault=='creation':g.owner['creation_ticks']+=100
    elif fault=='command':g.owner['command_sha256']='b'*64
    elif fault=='repository':g.owner['repository_sha256']='b'*64
    elif fault=='signature':b.proof['mac']='0'*64
    elif fault=='idle':
        b.idle=lambda:{'active_descendants':1,'unresolved_writers':0,'identity_verified':True}
        with pytest.raises(ValueError):b.verify_drained()
        assert g.phase=='HOLD';return
    elif fault=='direct-job':
        with m.loop('slow-maintenance'):
            with pytest.raises(ValueError):
                with m.job(cmd):pass
        assert g.phase=='HOLD';return
    elif fault=='alternate-manager':
        alt=MaintenanceObservation(launches=launch,native=m.native,ancestry=m.ancestry,
            manifest={n:[(cmd,m.manifest[n][cmd][0])] for n in LOOPS},retirement=m.retirement)
        with pytest.raises(ValueError):
            with alt.loop('slow-maintenance'):pass
        assert g.phase=='HOLD';return
    with pytest.raises(ValueError):b.verify()
    assert g.phase=='HOLD'


def test_job_and_log_reader_ticket_accounting(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts);b,o,g,m,launch,cmd=parts
    with runner.supervisor_job(cmd):
        ticket=b.ticket();result=[]
        def read():
            with b.writer(ticket):runner.run_admitted_job(['log'],lambda:result.append(True))
        t=threading.Thread(target=read);t.start();t.join(5)
        assert not t.is_alive() and result==[True] and len(g.jobs)==1
        with m.loop('slow-maintenance'),m.job(cmd) as ch:
            ch.phase='OBSERVED';ch.process=SimpleNamespace(pid=9,poll=lambda:0)
    assert not g.jobs
    with pytest.raises(ValueError):
        with b.writer(ticket):pass


def test_alternate_registry_cannot_replace_installed_binding(tmp_path,monkeypatch):
    a=tmp_path/'a';c=tmp_path/'c';a.mkdir();c.mkdir()
    parts=build(a);install(monkeypatch,parts)
    other=build(c)
    monkeypatch.setattr(runner,'LAUNCH_OBSERVATION',other[1])
    with pytest.raises(ValueError):runner.run_admitted_job(['unknown-registry'],lambda:pytest.fail('Must not run'))
    assert parts[2].phase=='HOLD'


def test_failed_log_reader_cannot_be_reported_as_completed(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts);b,o,g,*_=parts
    errors=[]
    with runner.supervisor_job(['parent']):
        ticket=b.ticket()
        def read():
            try:
                with b.writer(ticket):raise RuntimeError('lost write')
            except ValueError:errors.append('HOLD')
        t=threading.Thread(target=read);t.start();t.join(5)
        assert not t.is_alive() and errors==['HOLD']
    assert g.phase=='HOLD' and not g.jobs


def test_unavailable_idle_witness_latches_hold(tmp_path,monkeypatch):
    parts=build(tmp_path);install(monkeypatch,parts);exercise(parts)
    def unavailable():raise OSError('Independent witness disconnected')
    parts[0].idle=unavailable
    with pytest.raises(ValueError):parts[0].verify_drained()
    assert parts[2].phase=='HOLD'


@pytest.mark.parametrize('registration_fails',[False,True])
def test_actual_nested_dispatch_registers_before_private_release(tmp_path,monkeypatch,registration_fails):
    # Execute the unchanged AST body with inert captures; no subprocess is created.
    tree=ast.parse((ROOT/'scripts/run_genesis_service.py').read_text())
    fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='run_unfenced')
    order=[];proc=SimpleNamespace(pid=9,stdin=SimpleNamespace(close=lambda:order.append('private-pipe-closed')))
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:proc)
    class EndProbe(RuntimeError):pass
    def register(p,command):
        assert p is proc and command==['authenticated-wrapper'];order.append('native-registered')
        if registration_fails:raise EndProbe('No verified native ownership')
    def release(p,command):
        assert order==['native-registered'];order.append('private-release');raise EndProbe()
    ns={'subprocess':subprocess,'os':os,'root':tmp_path,'env':{},'name':'maintain',
        'COOPERATIVE_SUPERVISOR':SimpleNamespace(phase='RUNNING'),
        'COOPERATIVE_CHILDREN':SimpleNamespace(register=register),'COOPERATIVE_WEB':None,
        'MAINTENANCE_BINDING':object(),'LAUNCH_OBSERVATION':SimpleNamespace(
            child_command=lambda cmd:['authenticated-wrapper'],private_pipe=True,child_started=release)}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(ROOT/'scripts/run_genesis_service.py'),
        'exec',flags=__future__.annotations.compiler_flag),ns)
    with pytest.raises(EndProbe):ns['run_unfenced'](['synthetic-command'])
    assert order==(['native-registered','private-pipe-closed'] if registration_fails else ['native-registered','private-release'])


@pytest.mark.skipif(os.name!='nt',reason='Native Windows process witness required')
def test_native_isolated_loop_helper_process_retirement(tmp_path):
    Job=pytest.importorskip('scripts.genesis_native_descendants').OwnedDescendantJob
    from scripts.genesis_private_child_entry import native
    driver=tmp_path/'driver.py'
    driver.write_text('''import sys,json,os
from pathlib import Path
from test_genesis_maintenance_binding import build,exercise
from scripts import run_genesis_service as runner
print('READY',flush=True)
if sys.stdin.readline().strip()!='ISOLATED-WITNESS-READY':raise RuntimeError('No parent witness')
parts=build(Path(sys.argv[1]),native=True);b,o,g,*_=parts
runner.LAUNCH_OBSERVATION=o;runner.COOPERATIVE_SUPERVISOR=g
runner.install_maintenance_binding(b);o.enter('maintain',os.getpid())
print(json.dumps(exercise(parts)),flush=True)
''')
    env={**os.environ,'PYTHONPATH':os.pathsep.join([str(ROOT),str(ROOT/'tests'),str(ROOT/'.venv/Lib/site-packages')])}
    p=subprocess.Popen([sys._base_executable,str(driver),str(tmp_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    witness=None
    try:
        assert p.stdout.readline().strip()=='READY'
        row=native(p.pid);owner={'pid':p.pid,'creation_ticks':ticks(p.pid),'service':'maintain','command_sha256':row['command_sha256'],
            'repository_sha256':hashlib.sha256(str(ROOT).encode()).hexdigest()}
        def verify(pid):return {**owner,'creation_ticks':ticks(pid),'command_sha256':native(pid)['command_sha256']}
        witness=Job(p,owner,verify)
        out,err=p.communicate('ISOLATED-WITNESS-READY\n',timeout=60)
        assert p.returncode==0,err
        proof=witness.verified_exit();assert proof['active_processes']==0 and proof['root_exit_code']==0
        result=json.loads(out);assert result['phase']=='QUIESCED' and result['threads_exited']
        (tmp_path/'native-proof.json').write_text(json.dumps({'scope':'ACTUAL_RUNNER_HELPERS_NOT_FULL_MAIN_OR_CROSS_PROCESS_COORDINATOR','result':result,'kernel':proof},indent=2))
    finally:
        if p.poll() is None:(tmp_path/'HOLD-process.json').write_text(json.dumps({'pid':p.pid,'reason':'No forced cleanup authorized'}))
        if witness is not None:witness.close()
