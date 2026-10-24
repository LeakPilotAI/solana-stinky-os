"""Actual main entry, with inert children and no production dependency access.

These tests prove scheduling/admission behavior, NOT native authentication or SQL
recovery. Native witnesses and real jobs require a separately certified harness.
"""
from contextlib import contextmanager
import io
import threading
from types import SimpleNamespace
import sys

import pytest

from scripts import run_genesis_service as runner
from test_genesis_maintenance_binding import build, install


@pytest.mark.parametrize('fault', ['normal', 'watchdog', 'health-write', 'child-registration'])
def test_actual_main_concurrent_dispatch_and_cooperative_drain(tmp_path, monkeypatch, fault):
    root=tmp_path/'isolated'; scripts=root/'scripts'; scripts.mkdir(parents=True)
    (root/'docker-compose.yml').write_text('services: {}')
    parts=build(tmp_path); binding,observer,gate,manager,*_=parts
    install(monkeypatch,parts,entered=False)
    monkeypatch.setattr(runner,'__file__',str(scripts/'run_genesis_service.py'))
    monkeypatch.setattr(runner,'restore_search_path',lambda:None)
    monkeypatch.setattr(sys,'argv',['isolated-main','--name','maintain'])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner,'CORE_HEALTH',())  # Never probe production listeners.
    effects=[]; errors=[]; waits=set(); ready=threading.Event(); lock=threading.Lock()
    thread_errors=[]
    monkeypatch.setattr(threading,'excepthook',lambda args:thread_errors.append(type(args.exc_value).__name__))
    # The real job admission is deliberately replaced with an inert fixture. This
    # does not certify a private handshake, native ownership, or business writes.
    @contextmanager
    def job(command):
        assert gate.jobs
        effects.append(('job',tuple(command)))
        yield
    monkeypatch.setattr(observer,'job',job)
    monkeypatch.setattr(observer,'child_command',lambda c:c)
    monkeypatch.setattr(observer,'child_started',lambda p,c:effects.append(('private-fixture',p.pid)))
    class Process:
        counter=0
        def __init__(self,cmd,**kwargs):
            assert kwargs['cwd']==str(root) and gate.jobs
            with lock: Process.counter+=1; self.pid=Process.counter
            self.stdout=io.StringIO('synthetic child output\n');self.stdin=io.StringIO()
        def poll(self):return 0
        def wait(self):return 0
    monkeypatch.setattr(runner.subprocess,'Popen',Process)
    def register(p,c):
        assert gate.jobs
        if fault=='child-registration':
            ready.set()
            raise RuntimeError('Synthetic native registration unavailable')
        effects.append(('registered',p.pid))
    monkeypatch.setattr(runner,'COOPERATIVE_CHILDREN',SimpleNamespace(register=register,verify_exited=lambda p:effects.append(('exit',p.pid))))
    def watchdog(r,d,run):
        assert r==root and gate.jobs
        effects.append(('watchdog',True))
        if fault=='watchdog':raise RuntimeError('Synthetic ownership unavailable')
    monkeypatch.setattr(runner,'recover_watch_dependencies',watchdog)
    def state(path,payload):
        assert path.parent==root/'logs' and gate.jobs
        effects.append(('file',path.name))
        if fault=='health-write' and path.name=='runtime-state.json':
            ready.set()
            raise OSError('Synthetic storage unavailable')
    monkeypatch.setattr(runner,'write_state',state)
    # Actual main retains all three production cadence arguments. Only the
    # fixture wait implementation is shortened; it never sleeps to infer drain.
    def wait(seconds):
        with lock:
            waits.add(seconds)
            if waits=={10,60,21600}:ready.set()
        gate.stop_event.wait(10)
    monkeypatch.setattr(runner,'supervisor_wait',wait)
    def drain():
        try:
            assert ready.wait(10),'Actual main did not reach all three loop waits'
            if fault in ('health-write','child-registration'):
                # The operation's context must latch HOLD before cleanup. Do not
                # manufacture a successful drain for the deliberately failed job.
                return
            gate.quiesce({'request_id':'b'*32,'manifest_sha256':gate.manifest()},timeout=10)
        except BaseException as exc:errors.append(exc);gate.stop_event.set()
    controller=threading.Thread(target=drain,name='isolated-main-controller');controller.start()
    try:
        if fault in ('health-write','child-registration'):
            with pytest.raises((RuntimeError,ValueError),match='HOLD'):
                runner.main()
        else:code=runner.main()
    finally:
        gate.stop_event.set();controller.join(15)
        # Exact threads registered by the fixture gate only; no process signals.
        for row in list(gate.loops.values()):
            if row['thread'] is not threading.current_thread():row['thread'].join(5)
    assert not controller.is_alive()
    assert all(row['done'] for row in gate.loops.values())
    assert not gate.jobs and not manager.active
    assert (root/'logs/maintain.log').is_file()
    if fault in ('health-write','child-registration'):
        assert gate.phase=='HOLD' and gate.stop_event.is_set()
        assert not errors
        assert all(row['thread'] is threading.current_thread() or not row['thread'].is_alive() for row in gate.loops.values())
    else:
        assert waits=={10,60,21600} and not thread_errors
        assert (root/'logs/v2-pass-provenance.jsonl').is_file()
        assert not errors and code==0 and gate.phase=='QUIESCED'
        assert binding.verify_drained()['lifecycle_authorized'] is False
        commands=[row[1] for row in effects if row[0]=='job']
        assert len(commands)==6
        assert any(c[-1]=='learn-success' for c in commands)
        assert any(c[-1]=='recompute-performance' for c in commands)
        assert sum(any('run_intelligence_' in str(part) for part in c) for c in commands)==4
        assert sum(row[0]=='exit' for row in effects)==6
        assert ('file','runtime-state.json') in effects
        assert ('watchdog',True) in effects
