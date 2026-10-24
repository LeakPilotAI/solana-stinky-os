"""Explicit private Python child entry, never selected by ordinary startup."""
import json
import os
import sys
import hashlib
import subprocess

from scripts.genesis_background_ownership import MODULES
from scripts.genesis_launch_provenance import descriptor, authenticated, encoded, signed
from scripts.genesis_child_observation import PrivateChildReceiver, target


def native_many(pids):
    # One fresh before/after PID bracket per phase, not a cached census.
    if (os.name!='nt' or not isinstance(pids,tuple) or not 1<=len(pids)<=6 or
            len(set(pids))!=len(pids) or any(type(pid) is not int or not 0<pid<2**32 for pid in pids)):
        raise ValueError('Exact bounded Windows PIDs required')
    ids=','.join(str(pid) for pid in pids)
    script=("$ErrorActionPreference='Stop';$rows=@(1..2|ForEach-Object {foreach($targetId in @("+ids+")){"
        "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$targetId) -OperationTimeoutSec 3;"
        "if(!$p){throw 'Missing owner'};@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;"
        "created=$p.CreationDate.ToUniversalTime().ToString('o');executable=[string]$p.ExecutablePath;"
        "command=[string]$p.CommandLine}}});ConvertTo-Json -InputObject $rows -Compress")
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
                          capture_output=True,timeout=10)
    if result.returncode or len(result.stdout)>131072*len(pids):
        raise ValueError('Bounded native identity unavailable')
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(rows,list) or len(rows)!=2*len(pids):raise ValueError('Native identity bracket incomplete')
    phases=[]
    for offset in (0,len(pids)):
        identities={}
        for row in rows[offset:offset+len(pids)]:
            command=row.pop('command')
            if (not isinstance(command,str) or not command or len(command)>32768 or
                    row['pid'] not in pids or row['pid'] in identities):
                raise ValueError('Native command identity unavailable')
            row['command_sha256']=hashlib.sha256(command.encode()).hexdigest()
            identities[row['pid']]=descriptor(row)
        if set(identities)!=set(pids):raise ValueError('Missing native PID')
        phases.append(identities)
    if phases[0]!=phases[1]:raise ValueError('Native child bootstrap snapshot unstable')
    return phases[1]


def native(pid):
    if os.name=='nt' and type(pid) is int and pid==os.getpid():
        from scripts.genesis_self_native import current
        return current()
    return native_many((pid,))[pid]


native.batch=native_many


def read_frame():
    raw = sys.stdin.buffer.readline(16385)
    if not raw.endswith(b'\n') or len(raw) > 16384:
        raise ValueError('Private frame missing or outside bound')
    return json.loads(raw)


def main():
    try:
        maintenance=len(sys.argv)>=5 and sys.argv[1:3]==['maintain','--job']
        if not maintenance and (len(sys.argv) != 2 or sys.argv[1] not in MODULES):
            raise ValueError('Unsupported private child service')
        service = sys.argv[1]
        job_args=sys.argv[3:] if maintenance else None
        print(json.dumps({'kind':'genesis-private-child-ready-v1','pid':os.getpid()}),flush=True)
        envelope = read_frame()
        if set(envelope) != {'launch','frame'}: raise ValueError('Private envelope malformed')
        frame = bytes.fromhex(envelope['frame'])
        receiver = PrivateChildReceiver(service=service, launch=envelope['launch'],native=native,
            ancestry=lambda child,parent: child['parent_pid']==parent['pid'])
        # Optional exact lineage is authenticated and independently re-read.
        proof = receiver.receive(frame)
        print(json.dumps(proof),flush=True)
        key = bytes.fromhex(json.loads(frame)['key'])
        receiver.complete(read_frame(),lambda:True)
        print(json.dumps(receiver.completion),flush=True)
        confirmation = authenticated(key,read_frame())
        if encoded(confirmation) != encoded({'kind':'genesis-child-confirmed-v1',
                                             'target':target(receiver.completion)}):
            raise ValueError('Parent did not confirm child installation')
        # Recheck native identities after the final private round trip.
        receiver._current(receiver.proof['body'])
        prepared_job=None
        if maintenance:
            from scripts.genesis_maintenance_observation import verify_job
            prepared_job=verify_job(receiver.proof['body'].get('work'),job_args)
        if receiver.now() >= receiver.proof['body']['expires_ns']:
            raise ValueError('Final child dispatch deadline exceeded')
        print(json.dumps(signed(key,{'kind':'genesis-child-dispatch-ready-v1',
                                    'target':target(receiver.completion)})),flush=True)
        continuation=authenticated(key,read_frame())
        if encoded(continuation)!=encoded({'kind':'genesis-child-observation-complete-v1',
                'target':target(receiver.completion),'lifecycle_authorized':False,'write_authorized':False}):
            raise ValueError('Final wrapper observation not confirmed')
        if receiver.now()>=receiver.proof['body']['expires_ns']:
            raise ValueError('Entry continuation deadline exceeded')
        del key, frame, envelope
        import runpy
        if maintenance:
            mode,job_target,args=prepared_job
            sys.argv=[job_target,*args]
            if mode=='module':runpy.run_module(job_target,run_name='__main__',alter_sys=True)
            else:
                from pathlib import Path
                sys.path.insert(0,str(Path(job_target).resolve().parent))
                runpy.run_path(job_target,run_name='__main__')
        else:
            sys.argv = [MODULES[service]]
            runpy.run_module(MODULES[service],run_name='__main__',alter_sys=True)
        return 0
    except Exception:
        # No exception text, raw frame, command, key or authentication material.
        sys.stderr.write('Private child bootstrap/application failed; HOLD\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
