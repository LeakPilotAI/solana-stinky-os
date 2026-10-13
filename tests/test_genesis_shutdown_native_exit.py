"""Explicit Windows-only native child fixture. Never signals live processes."""
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import run_genesis_service as runner
from scripts import safe_genesis_start as safe
from scripts.guarded_redis_migration import NativePause
from scripts.genesis_child_exit import ChildRegistry
from scripts.genesis_process_diagnostics import native_identity
from scripts.genesis_supervisor_admission import SupervisorAdmission
from scripts.redis_production_adapters import DurableJournal
import start_genesis as launcher


@pytest.mark.parametrize('scenario',['normal','crash','orphan','identity-change'])
def test_native_child_exit_and_actual_supervisor_admission(tmp_path,monkeypatch,scenario):
    if os.name!='nt' or os.environ.get('GENESIS_SHUTDOWN_NATIVE_CERTIFICATION')!='isolated-checkpoint77':
        pytest.skip('Explicit isolated native certification required')
    adapter=NativePause();pid=os.getpid();ticks,image=native_identity(adapter,pid)
    rows={r[0]:r for r in launcher.list_win_processes()}
    owner={'pid':pid,'creation_ticks':ticks,'service':'fixture',
        'command_sha256':hashlib.sha256(rows[pid][3].encode()).hexdigest(),
        'repository_sha256':hashlib.sha256(str(runner._SCRIPTS.parent).encode()).hexdigest()}
    def verify_owner():
        assert native_identity(adapter,pid)==(ticks,image)
        return dict(owner)
    journal=DurableJournal(tmp_path/'native-child.jsonl')
    def persist(row):journal.persist(row);return journal.previous
    gate=SupervisorAdmission(owner,generation=1,verify_native=verify_owner,persist=persist)
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    monkeypatch.setattr(runner,'COOPERATIVE_CHILDREN',None)
    runner.install_cooperative_supervisor(gate)
    handles={};descendants=[]
    def capture(proc,command):
        native={r[0]:r for r in launcher.list_win_processes()}[proc.pid]
        assert native[1]==pid
        assert safe.command_tokens(native[3])==command
        handle=adapter.open(proc.pid);handles[proc.pid]=handle
        return {'pid':proc.pid,'parent_pid':pid,'creation_ticks':adapter.creation(handle),
            'command_sha256':hashlib.sha256(json.dumps(command,separators=(',',':')).encode()).hexdigest(),
            'repository_sha256':owner['repository_sha256']}
    def exit_code(handle):
        from ctypes import wintypes
        code=wintypes.DWORD()
        method=adapter.kernel.GetExitCodeProcess
        method.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        assert method(handle,ctypes.byref(code))
        return code.value
    def inspect(proc,record):
        assert adapter.creation(handles[proc.pid])==record['creation_ticks']
        code=exit_code(handles[proc.pid])
        return {'owner':record,'exited':code!=259,'exit_code':code,
                'descendants_exited':all(exit_code(h)!=259 for h in descendants)}
    registry=ChildRegistry(gate,capture=capture,inspect=inspect,persist=persist)
    runner.install_child_registry(registry)
    script=tmp_path/'owned-child.py'
    script.write_text("import sys,subprocess\n"+
        "if sys.argv[1]=='orphan':\n p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)']); print(p.pid,flush=True)\n"+
        "else: print('ready',flush=True)\n"+
        "sys.stdin.readline()\nsys.exit(71 if sys.argv[1]=='crash' else 0)\n")
    command=[sys._base_executable,str(script),scenario]
    proc=None
    try:
        def actual_child_job():
            nonlocal proc
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
            registry.register(proc,command)
            ready=proc.stdout.readline().strip()
            if scenario=='orphan':
                child_pid=int(ready)
                native={r[0]:r for r in launcher.list_win_processes()}[child_pid]
                assert native[1]==proc.pid
                descendants.append(adapter.open(child_pid))
            assert proc.poll() is None
            assert inspect(proc,registry.children[proc.pid]['owner'])['exited'] is False
            proc.stdin.write('finish\n');proc.stdin.flush();proc.wait(timeout=5)
            if scenario=='identity-change':registry.children[proc.pid]['owner']['creation_ticks']+=1
            if scenario=='normal':assert registry.verify_exited(proc)
            else:
                with pytest.raises((RuntimeError,AssertionError)):registry.verify_exited(proc)
        runner.run_admitted_job(command,actual_child_job)
        if scenario=='normal':
            result=gate.quiesce({'request_id':'f'*32,'manifest_sha256':gate.manifest()})
            assert result['phase']=='QUIESCED'
            with pytest.raises(RuntimeError):runner.run_admitted_job(command,lambda:pytest.fail('respawn'))
        else:assert gate.phase=='HOLD'
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.stdin.write('finish\n');proc.stdin.flush();proc.wait(timeout=5)
            proc.stdin.close();proc.stdout.close();proc.stderr.close()
        deadline=time.monotonic()+5
        while any(exit_code(h)==259 for h in descendants):
            assert time.monotonic()<deadline;time.sleep(.01)
        for handle in [*handles.values(),*descendants]:adapter.close(handle)
        journal.close()
