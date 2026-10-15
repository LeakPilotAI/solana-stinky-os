"""Explicit private Python child entry, never selected by ordinary startup."""
import json
import os
import sys
import hashlib
import subprocess

from scripts.genesis_background_ownership import MODULES
from scripts.genesis_launch_provenance import descriptor, authenticated, encoded, signed
from scripts.genesis_child_observation import PrivateChildReceiver, target


def native(pid):
    # Identity verification does not require a global socket census. Re-read the
    # exact PID twice; never cache a prior census or infer identity from a count.
    if os.name != 'nt' or type(pid) is not int or not 0 < pid < 2**32:
        raise ValueError('Exact Windows native PID required')
    script = ("$ErrorActionPreference='Stop';$rows=@(1..2 | ForEach-Object {"
        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(pid)+"' -OperationTimeoutSec 3;"
        "if (!$p) {throw 'Missing owner'};"
        "@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;"
        "created=$p.CreationDate.ToUniversalTime().ToString('o');"
        "executable=[string]$p.ExecutablePath;command=[string]$p.CommandLine}});"
        "ConvertTo-Json -InputObject $rows -Compress")
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
                            capture_output=True,timeout=10)
    if result.returncode or len(result.stdout)>131072:
        raise ValueError('Bounded native identity unavailable')
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(rows,list) or len(rows)!=2:
        raise ValueError('Native identity bracket incomplete')
    identities=[]
    for row in rows:
        command=row.pop('command')
        if not isinstance(command,str) or not command or len(command)>32768 or row['pid']!=pid:
            raise ValueError('Native command identity unavailable')
        row['command_sha256']=hashlib.sha256(command.encode()).hexdigest()
        identities.append(descriptor(row))
    if identities[0] != identities[1]:
        raise ValueError('Native child bootstrap snapshot unstable')
    return identities[1]


def read_frame():
    raw = sys.stdin.buffer.readline(16385)
    if not raw.endswith(b'\n') or len(raw) > 16384:
        raise ValueError('Private frame missing or outside bound')
    return json.loads(raw)


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in MODULES:
            raise ValueError('Unsupported private child service')
        service = sys.argv[1]
        print(json.dumps({'kind':'genesis-private-child-ready-v1','pid':os.getpid()}),flush=True)
        envelope = read_frame()
        if set(envelope) != {'launch','frame'}: raise ValueError('Private envelope malformed')
        frame = bytes.fromhex(envelope['frame'])
        receiver = PrivateChildReceiver(service=service, launch=envelope['launch'],native=native,
            ancestry=lambda child,parent: child['parent_pid']==parent['pid'])
        # Direct-parent mode intentionally rejects venv-wrapper/grandchild cases.
        # Do not replace it with a process-count or name-based ancestry shortcut.
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
        if receiver.now() >= receiver.proof['body']['expires_ns']:
            raise ValueError('Final child dispatch deadline exceeded')
        print(json.dumps(signed(key,{'kind':'genesis-child-dispatch-ready-v1',
                                    'target':target(receiver.completion)})),flush=True)
        del key, frame, envelope
        import runpy
        sys.argv = [MODULES[service]]
        runpy.run_module(MODULES[service],run_name='__main__',alter_sys=True)
        return 0
    except Exception:
        # No exception text, raw frame, command, key or authentication material.
        sys.stderr.write('Private child bootstrap/application failed; HOLD\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
