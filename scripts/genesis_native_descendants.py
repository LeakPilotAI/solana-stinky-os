"""Owned Windows job membership proof; never kills, stops or suspends processes.

Attach only a freshly spawned, independently verified child before authorizing
its work. No breakaway/kill-on-close flags are enabled. Missing native proof HOLDs.
"""
import ctypes
import os
from ctypes import wintypes


class Accounting(ctypes.Structure):
    _fields_=[('user',ctypes.c_longlong),('kernel',ctypes.c_longlong),
        ('period_user',ctypes.c_longlong),('period_kernel',ctypes.c_longlong),
        ('faults',wintypes.DWORD),('total',wintypes.DWORD),
        ('active',wintypes.DWORD),('terminated',wintypes.DWORD)]


class OwnedDescendantJob:
    def __init__(self, proc, owner, verify_native):
        if os.name!='nt' or owner['pid']!=proc.pid or verify_native(proc.pid)!=owner or proc.poll() is not None:
            raise RuntimeError('Fresh exact native child required before job assignment')
        self.proc=proc;self.owner=dict(owner);self.verify_native=verify_native
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        k=self.kernel
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];k.CreateJobObjectW.restype=wintypes.HANDLE
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        k.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
        k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        self.job=k.CreateJobObjectW(None,None)
        # AssignProcessToJobObject requires SET_QUOTA|TERMINATE access. This
        # module deliberately exposes no termination operation whatsoever.
        self.root=k.OpenProcess(0x0100|0x0001|0x1000,False,proc.pid)
        if not self.job or not self.root:
            self.close();raise RuntimeError('Native job/child handle unavailable')
        try:
            if self.creation()!=owner['creation_ticks'] or verify_native(proc.pid)!=owner:
                raise RuntimeError('Child identity changed before assignment')
            if not k.AssignProcessToJobObject(self.job,self.root):
                raise RuntimeError('Exact child cannot enter isolated descendant job')
            # A fresh unnamed job has no breakaway or kill-on-close policy.
            # Children inherit membership; terminal ActiveProcesses=0 proves
            # no orphan remains even when a short-lived PID evades a census.
        except BaseException:self.close();raise

    def creation(self):
        values=[wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.root,*[ctypes.byref(v) for v in values]):
            raise RuntimeError('Retained native creation identity unavailable')
        return (values[0].dwHighDateTime<<32)|values[0].dwLowDateTime

    def snapshot(self):
        data=Accounting()
        if not self.kernel.QueryInformationJobObject(self.job,1,ctypes.byref(data),ctypes.sizeof(data),None):
            raise RuntimeError('Complete kernel descendant membership unavailable')
        if self.creation()!=self.owner['creation_ticks'] or data.active>64 or data.total<1:
            raise RuntimeError('Native descendant identity/bound mismatch')
        code=wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.root,ctypes.byref(code)):
            raise RuntimeError('Native root exit evidence unavailable')
        return {'owner':dict(self.owner),'active_processes':data.active,'total_processes':data.total,
                'root_exit_code':code.value,'policy':'NO_KILL_NO_BREAKAWAY',
                'scope':'OWNED_KERNEL_DESCENDANTS_NOT_APPLICATION_WRITE_DRAIN'}

    def verified_exit(self):
        proof=self.snapshot()
        if proof['active_processes']!=0 or proof['root_exit_code']!=0 or self.proc.poll()!=0:
            raise RuntimeError('Native root/descendants not cleanly exited; HOLD')
        return proof

    def close(self):
        # No kill-on-close: a failed fixture is retained rather than destroyed.
        if getattr(self,'root',None):self.kernel.CloseHandle(self.root);self.root=None
        if getattr(self,'job',None):self.kernel.CloseHandle(self.job);self.job=None
