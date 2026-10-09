"""Fail-closed guards for an explicitly approved, reversible Redis migration.

No automatic container migration. The caller must supply verified native Genesis
process identities and establish a recovery boundary before controlling Docker.
"""
from __future__ import annotations
import ctypes
import os
from contextlib import contextmanager

SOURCE_VOLUME='project-genesis_redis-data'
DURABLE_VOLUME='project-genesis_redis-durable-data'

def verify_no_volume_writer(records,volume):
    for record in records:
        running=record.get('State',{}).get('Running')
        mounts=record.get('Mounts')
        if type(running)!=bool or not isinstance(mounts,list):
            raise RuntimeError('Container activity/mount inventory unavailable')
        if running and any(m.get('Name')==volume for m in mounts):
            raise RuntimeError('Volume already has an active container; do not start a second writer')

def verify_candidate(record,*,container_id,volume,port,image):
    if volume not in (DURABLE_VOLUME,'project-genesis_redis-proof56-data'):
        raise RuntimeError('Candidate volume outside approved migration scope')
    if record.get('Id')!=container_id or record.get('Image')!=image:
        raise RuntimeError('Candidate identity/image mismatch')
    labels=record.get('Config',{}).get('Labels') or {}
    if labels.get('com.docker.compose.project')!='project-genesis' or labels.get('com.docker.compose.service')!='redis':
        raise RuntimeError('Candidate ownership mismatch')
    if record.get('Config',{}).get('Cmd')!=['redis-server','/data/redis.conf']:
        raise RuntimeError('Candidate startup overrides persistence')
    mounts=record.get('Mounts',[])
    if len(mounts)!=1:raise RuntimeError('Candidate has unexpected additional mounts')
    if not any(m.get('Type')=='volume' and m.get('Name')==volume and m.get('Destination')=='/data' and m.get('RW') for m in mounts):
        raise RuntimeError('Candidate data volume mismatch')
    if any(m.get('Name')==SOURCE_VOLUME for m in mounts):
        raise RuntimeError('Original volume must not be mounted by candidate')
    bindings=record.get('HostConfig',{}).get('PortBindings',{}).get('6379/tcp') or []
    if bindings!=[{'HostIp':'127.0.0.1','HostPort':str(port)}]:
        raise RuntimeError('Candidate port isolation mismatch')

class NativePause:
    """Hold native handles so PID reuse cannot redirect suspend/resume operations."""
    def __init__(self):
        if os.name!='nt':raise RuntimeError('Windows-only process coordination')
        from ctypes import wintypes
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.nt=ctypes.WinDLL('ntdll')
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        self.nt.NtSuspendProcess.argtypes=[wintypes.HANDLE]
        self.nt.NtResumeProcess.argtypes=[wintypes.HANDLE]
        self.nt.NtSuspendProcess.restype=self.nt.NtResumeProcess.restype=ctypes.c_long

    def open(self,pid):
        handle=self.kernel.OpenProcess(0x0800|0x1000,False,pid)
        if not handle:raise RuntimeError('Native process pause access unavailable')
        return handle

    def creation(self,handle):
        from ctypes import wintypes
        times=[wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
            raise RuntimeError('Native creation identity unavailable')
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime

    def suspend(self,handle):
        if self.nt.NtSuspendProcess(handle)!=0:raise RuntimeError('Native process suspension failed')

    def resume(self,handle):
        if self.nt.NtResumeProcess(handle)!=0:raise RuntimeError('Native process resumption failed')

    def close(self,handle):self.kernel.CloseHandle(handle)

@contextmanager
def pause_verified_processes(identities,verify,adapter):
    """Verify argv/creation before suspension; always resume even after a failure.

    identities is an ordered list (PID, native creation ticks); supervisor roots
    precede children. Caller proves repository/service ancestry before this API.
    """
    opened=[];paused=[]
    try:
        for pid,creation in identities:
            verify(pid)
            handle=adapter.open(pid);opened.append(handle)
            if adapter.creation(handle)!=creation:raise RuntimeError('Process identity changed before pause')
            adapter.suspend(handle);paused.append(handle)
        yield
    finally:
        errors=[]
        for handle in reversed(paused):
            try:adapter.resume(handle)
            except Exception:errors.append(handle)
        for handle in opened:adapter.close(handle)
        if errors:raise RuntimeError('Process resumption incomplete; manual owned-process recovery required')
