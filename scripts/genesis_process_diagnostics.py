"""Bounded read-only native ownership snapshots; never controls processes.

Commands are consumed by existing ownership validators but only hashes and
verified roles are recorded. Missing identities and tree changes fail closed.
"""
from __future__ import annotations

import hashlib
import ctypes
import time
from scripts import safe_genesis_start as safe, safe_genesis_stop as stop

MAX_ROWS = 2048
MAX_SNAPSHOT_AGE_NS = 10_000_000_000


def native_identity(adapter, pid):
    """Read image/creation/aliveness from one handle, never a second PID lookup."""
    from ctypes import wintypes
    handle = adapter.open(pid)
    try:
        query = adapter.kernel.QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                          ctypes.POINTER(wintypes.DWORD)]
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not query(handle, 0, buffer, ctypes.byref(size)):
            raise RuntimeError('Native image path unavailable')
        code = wintypes.DWORD()
        active = adapter.kernel.GetExitCodeProcess
        active.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if not active(handle, ctypes.byref(code)) or code.value != 259:
            raise RuntimeError('Process exited during identity capture')
        return adapter.creation(handle), buffer.value
    finally:
        adapter.close(handle)


def capture_native(launcher, adapter):
    identities = {}
    def creation(pid):
        identities[pid] = native_identity(adapter, pid)
        return identities[pid][0]
    return owned_snapshot(launcher, safe.inventory(launcher), creation,
                          lambda pid: identities[pid][1])


def owned_snapshot(launcher, rows, creation, image_path):
    captured_at = time.monotonic_ns()
    if not rows or len(rows) > MAX_ROWS:
        raise RuntimeError('Process inventory unavailable or outside bound')
    if len({r[0] for r in rows}) != len(rows):
        raise RuntimeError('Duplicate native PID inventory')
    plan = stop.stop_plan(launcher, rows)
    selected = set(plan)
    nodes = {}
    for pid, parent, executable, command in rows:
        if pid not in selected:
            continue
        started = creation(pid)
        path = image_path(pid)
        if type(started) is not int or started <= 0 or not path:
            raise RuntimeError('Native creation/image identity unavailable')
        if safe.ntpath.basename(safe.windows_path(path)) != executable.casefold():
            raise RuntimeError('Native executable differs from inventory')
        roles = [name for name in safe.SERVICES
                 if safe.runner_command(executable, command, name) is not None]
        role = 'supervisor:' + roles[0] if len(roles) == 1 else 'owned-descendant'
        nodes[pid] = {'pid': pid, 'parent_pid': parent, 'creation_ticks': started,
                      'image_path': safe.windows_path(path), 'role': role,
                      'command_sha256': hashlib.sha256(command.encode('utf-8')).hexdigest()}
    return {'schema': 'genesis-native-process-snapshot-v1',
            'captured_at_monotonic_ns': captured_at,
            'inventory_rows': len(rows), 'nodes': sorted(nodes.values(), key=lambda n: n['pid'])}


def compare_snapshots(before, after):
    def validate(snapshot):
        if not isinstance(snapshot, dict) or set(snapshot) != {'schema', 'inventory_rows', 'nodes', 'captured_at_monotonic_ns'} or snapshot.get('schema') != 'genesis-native-process-snapshot-v1':
            raise RuntimeError('Process snapshot schema unavailable')
        if type(snapshot['captured_at_monotonic_ns']) is not int or snapshot['captured_at_monotonic_ns'] <= 0:
            raise RuntimeError('Process snapshot acquisition time unavailable')
        if type(snapshot['inventory_rows']) is not int or not 1 <= snapshot['inventory_rows'] <= MAX_ROWS:
            raise RuntimeError('Process inventory coverage unavailable')
        nodes = snapshot.get('nodes')
        if not isinstance(nodes, list) or len(nodes) > MAX_ROWS:
            raise RuntimeError('Process snapshot incomplete')
        mapping = {}
        required = {'pid', 'parent_pid', 'creation_ticks', 'image_path', 'role', 'command_sha256'}
        for node in nodes:
            if not isinstance(node, dict) or set(node) != required:
                raise RuntimeError('Process identity fields incomplete')
            if any(type(node[k]) is not int or node[k] < (1 if k != 'parent_pid' else 0)
                   for k in ('pid', 'parent_pid', 'creation_ticks')):
                raise RuntimeError('Process identity invalid')
            if any(not isinstance(node[k], str) or not node[k] for k in ('image_path', 'role', 'command_sha256')) or not safe.re.fullmatch('[0-9a-f]{64}', node['command_sha256']):
                raise RuntimeError('Process ownership identity incomplete')
            if node['pid'] in mapping:
                raise RuntimeError('Duplicate process identity')
            mapping[node['pid']] = node
        return mapping
    a, b = validate(before), validate(after)
    changed = [{'pid': p, 'fields': [k for k in a[p] if a[p][k] != b[p][k]],
                'before': a[p], 'after': b[p]}
               for p in sorted(a.keys() & b.keys()) if a[p] != b[p]]
    added, removed = [b[p] for p in sorted(b.keys()-a.keys())], [a[p] for p in sorted(a.keys()-b.keys())]
    return {'status': 'CHANGED' if added or removed or changed else 'MATCH',
            'added': added, 'removed': removed, 'changed': changed}


def verify_unchanged(before, after):
    difference = compare_snapshots(before, after)
    now = time.monotonic_ns()
    first, last = before['captured_at_monotonic_ns'], after['captured_at_monotonic_ns']
    if not first <= last <= now or now - first > MAX_SNAPSHOT_AGE_NS:
        raise RuntimeError('Process snapshots stale or acquisition ordering invalid; not certified')
    if difference['status'] != 'MATCH':
        raise RuntimeError('Native process ownership/tree changed; quiescence not certified')
    return difference
