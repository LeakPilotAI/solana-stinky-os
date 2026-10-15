"""Read-only process/listener evidence. Never grants lifecycle authority.

Two bounded native censuses bracket socket acquisition. Raw command lines remain
in memory; results publish hashes. Snapshot agreement is observation, not proof
of historical ancestry, authenticated launch provenance or absence between polls.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import ntpath
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import time

SERVICES = ('event-log', 'api', 'sentinel', 'collector', 'entities', 'web', 'maintain')
PORTS = {'event-log': 8002, 'api': 8010, 'web': 3000}
MODULES = {'event-log': 'event_log.cli', 'api': 'stinky_api.cli',
           'sentinel': 'sentinel.cli', 'collector': 'post_migration.cli',
           'entities': 'entity_resolver.cli'}
MAX_ROWS = 4096


def norm(value):
    return ntpath.normpath(value).casefold() if isinstance(value, str) else ''


def tokens(command):
    """Use Windows' argument parser, not shell splitting or substring ownership."""
    from ctypes import wintypes
    count = ctypes.c_int()
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        raise ValueError('Command identity unavailable')
    try:
        if not 1 <= count.value <= 128:
            raise ValueError('Command token bound')
        return [pointer[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(pointer)


def capture(extra_ports=()):
    if os.name != 'nt':
        raise RuntimeError('Native Windows evidence required')
    if (not isinstance(extra_ports, tuple) or len(extra_ports) > 8 or
            any(type(p) is not int or not 1 <= p <= 65535 for p in extra_ports)):
        raise ValueError('Invalid extra observation ports')
    script = r'''
$ErrorActionPreference='Stop'
function Census {
 $rows=@(Get-CimInstance Win32_Process -OperationTimeoutSec 10)
 if ($rows.Count -gt 4096 -or $rows.Count -eq 0) { throw 'Process inventory bound' }
 @($rows | ForEach-Object {
  if (([string]$_.CommandLine).Length -gt 32768) { throw 'Command bound' }
  [pscustomobject]@{pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;
   created=if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString('o')} else {$null};
   executable=[string]$_.ExecutablePath;command=[string]$_.CommandLine}
 })
}
$before=@(Census)
$sockets=@(Get-NetTCPConnection -ErrorAction Stop | Where-Object {
 $_.LocalPort -in @(__PORTS__) -or $_.RemotePort -in @(__PORTS__)
} | ForEach-Object { [pscustomobject]@{pid=[int]$_.OwningProcess;state=[string]$_.State;
 address=[string]$_.LocalAddress;port=[int]$_.LocalPort;
 remote_port=[int]$_.RemotePort;remote_address=[string]$_.RemoteAddress} })
if ($sockets.Count -gt 4096) { throw 'Socket inventory bound' }
$after=@(Census)
@{before=$before;after=$after;sockets=$sockets} | ConvertTo-Json -Depth 5 -Compress
'''
    script = script.replace('__PORTS__', ','.join(map(str, (3000, 8002, 8010, 6380, 5433, 9010) + extra_ports)))
    started = time.monotonic()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, timeout=30)
    if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
        raise RuntimeError('Native process/socket capture unavailable or outside bound')
    data = json.loads(result.stdout.decode('utf-8-sig'))
    for phase in ('before', 'after'):
        for row in data[phase]:
            command = row.pop('command')
            row['argv'] = tokens(command) if command else []
            row['command_sha256'] = hashlib.sha256(command.encode()).hexdigest()
    data['elapsed_seconds'] = time.monotonic() - started
    return data


def listener_identity(data, pid, port):
    """Match an actual socket owner to unchanged bracketing native descriptors."""
    before = [r for r in data['before'] if r['pid'] == pid]
    after = [r for r in data['after'] if r['pid'] == pid]
    if len(before) != 1 or len(after) != 1 or before[0] != after[0]:
        return False
    row = before[0]
    return bool(row.get('created') and row.get('executable') and row.get('command_sha256') and
                any(s['pid'] == pid and s['port'] == port and s['state'] == 'Listen'
                    for s in data['sockets']))


def assess(data, root):
    """Fail closed; root is trusted configuration, never inferred from a process."""
    holds = []
    def inventory(rows):
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError('Process census missing or outside bound')
        result = {}
        for row in rows:
            if (not isinstance(row, dict) or type(row.get('pid')) is not int or
                    row['pid'] < 0 or row['pid'] in result or
                    type(row.get('parent_pid')) is not int or row['parent_pid'] < 0 or
                    not isinstance(row.get('executable'), str) or
                    (row.get('created') is not None and not isinstance(row['created'], str)) or
                    not isinstance(row.get('command_sha256'), str) or
                    not re.fullmatch('[0-9a-f]{64}', row['command_sha256']) or
                    not isinstance(row.get('argv'), list) or
                    len(row['argv']) > 128 or
                    any(not isinstance(a, str) for a in row['argv'])):
                raise ValueError('Invalid or duplicated process identity')
            result[row['pid']] = row
        return result
    try:
        before, after = inventory(data['before']), inventory(data['after'])
        sockets = data['sockets']
        if (not isinstance(sockets, list) or len(sockets) > MAX_ROWS or
                type(data['elapsed_seconds']) not in (int, float) or
                not 0 <= data['elapsed_seconds'] <= 30):
            raise ValueError('Socket census missing, stale or outside bound')
    except (KeyError, TypeError, ValueError):
        return {'status': 'HOLD', 'holds': ['INVALID_NATIVE_EVIDENCE'],
                'lifecycle_authorized': False, 'services': [], 'listeners': []}
    runner = norm(ntpath.join(str(root), 'scripts', 'run_genesis_service.py'))
    images = {norm(ntpath.join(str(root), '.venv', 'Scripts', n))
              for n in ('python.exe', 'pythonw.exe')}
    roots = {}
    candidates = set()
    for pid, row in after.items():
        args = row['argv']
        if any(norm(arg) == runner for arg in args):
            candidates.add(pid)
            if (len(args) == 4 and norm(args[0]) == norm(row['executable']) and
                    norm(args[0]) in images and norm(args[1]) == runner and
                    args[2] == '--name' and args[3] in SERVICES):
                roots[pid] = args[3]
            else:
                holds.append('UNVERIFIED_SUPERVISOR')
        # Known module invocation without a known repository runner is a possible
        # bypass/orphan, not a Genesis-owned process or a termination target.
        if any(a in MODULES.values() for a in args):
            candidates.add(pid)
    owners = dict(roots)
    for _ in range(32):
        added = {p: owners[r['parent_pid']] for p, r in after.items()
                 if p not in owners and r['parent_pid'] in owners}
        if not added:
            break
        owners.update(added)
    for p in candidates - owners.keys():
        holds.append('POSSIBLE_ORPHAN_OR_BYPASS')
    relevant = set(owners) | candidates
    service_rows = []
    for service in SERVICES:
        pids = [p for p, name in roots.items() if name == service]
        # Wrapper chains may be legitimate, but require separate native proof.
        # Never silently collapse a duplicate claim into one trusted supervisor.
        if len(pids) > 1:
            holds.append('MULTIPLE_SUPERVISOR_CLAIMS')
        service_rows.append({'service': service, 'supervisor_pids': pids,
                             'state': 'OBSERVED' if len(pids) == 1 else 'MISSING_OR_CONFLICT',
                             'launch_provenance': 'UNATTESTED'})
    listener_rows = []
    try:
        for socket in sockets:
            if (type(socket.get('pid')) is not int or type(socket.get('port')) is not int or
                    not 0 <= socket['port'] <= 65535 or not isinstance(socket.get('state'), str)):
                raise ValueError('Socket identity invalid')
            if socket['state'] == 'Listen' and socket['port'] in PORTS.values():
                service = next(s for s, port in PORTS.items() if port == socket['port'])
                pid = socket['pid']; relevant.add(pid)
                belongs = owners.get(pid) == service
                if not belongs:
                    holds.append('FOREIGN_OR_UNVERIFIED_LISTENER')
                listener_rows.append({'service': service, 'pid': pid, 'port': socket['port'],
                                      'ancestry_match': belongs})
            if socket.get('remote_port') == 6380:
                relevant.add(socket['pid'])
                if socket['pid'] not in owners:
                    holds.append('UNATTRIBUTED_REDIS_CONNECTION')
    except (TypeError, ValueError, AttributeError):
        holds.append('INVALID_SOCKET_EVIDENCE')
    # Include ancestors so a reused/replaced parent cannot establish a false chain.
    for pid in list(relevant):
        seen = {pid}; current = pid
        for _ in range(32):
            row = after.get(current)
            if row is None:
                holds.append('MISSING_PROCESS'); break
            parent = row['parent_pid']
            if not parent:
                break
            if parent in seen:
                holds.append('AMBIGUOUS_ANCESTRY'); break
            seen.add(parent); relevant.add(parent); current = parent
        else:
            holds.append('ANCESTRY_BOUND_EXCEEDED')
    for pid in relevant:
        a, b = before.get(pid), after.get(pid)
        if a is None or b is None:
            holds.append('MISSING_OR_CHANGING_PROCESS'); continue
        if a != b:
            holds.append('PROCESS_IDENTITY_CHANGED')
        if not b.get('created') or not b.get('executable') or not b.get('command_sha256'):
            holds.append('INCOMPLETE_PROCESS_IDENTITY')
        else:
            try:
                created = datetime.fromisoformat(b['created'].replace('Z', '+00:00'))
                if created.tzinfo is None:
                    raise ValueError('Missing timezone')
                parent = after.get(b['parent_pid'])
                if parent and parent.get('created'):
                    parent_created = datetime.fromisoformat(parent['created'].replace('Z', '+00:00'))
                    if parent_created.tzinfo is None or parent_created > created:
                        raise ValueError('Parent created after child')
            except (ValueError, TypeError, AttributeError):
                holds.append('INVALID_CREATION_OR_PARENT_ORDER')
        if pid in owners:
            holds.append('LAUNCH_PROVENANCE_UNATTESTED')
            args = b['argv']
            if not args or norm(args[0]) != norm(b['executable']):
                holds.append('EXECUTABLE_COMMAND_MISMATCH')
            if pid not in roots:
                name = owners[pid]
                # This intentionally conservative subset cannot authorize arbitrary
                # descendants simply because they inherit a parent PID.
                known = (len(args) >= 3 and args[1] == '-m' and
                         args[2] == MODULES.get(name) and norm(args[0]) in images)
                if name == 'web' and len(args) >= 2:
                    known = (ntpath.basename(norm(b['executable'])) == 'node.exe' and
                             norm(args[1]) in {norm(ntpath.join(str(root), 'apps/web/node_modules/next/dist/bin/next')),
                             norm(ntpath.join(str(root), 'apps/web/node_modules/next/dist/server/lib/start-server.js'))})
                if not known:
                    holds.append('UNVERIFIED_DESCENDANT_COMMAND')
    # Previously present roots/children disappearing are not evidence of clean exit.
    for pid in before.keys() - after.keys():
        if any(norm(a) == runner or a in MODULES.values() for a in before[pid]['argv']):
            holds.append('PROCESS_DISAPPEARED_DURING_CAPTURE')
    return {'status': 'HOLD' if holds else 'NO_OWNED_RUNTIME_OBSERVED',
            'holds': sorted(set(holds)), 'lifecycle_authorized': False,
            'services': service_rows, 'listeners': listener_rows,
            'scope': 'BRACKETED_NATIVE_OBSERVATIONS_NOT_AUTHENTICATED_OWNERSHIP',
            'owned_tree_pids_observed': sorted(owners),
            'redis_socket_scope': 'HOST_SOCKET_ONLY_DOCKER_NAT_NOT_SERVER_CLIENT_ID'}


if __name__ == '__main__':
    try:
        result = assess(capture(), Path(__file__).resolve().parents[1])
    except Exception:
        result = {'status': 'HOLD', 'holds': ['NATIVE_CAPTURE_UNAVAILABLE'],
                  'lifecycle_authorized': False}
    print(json.dumps(result, sort_keys=True))
