"""Fresh current-process Windows identity. No remote reads, cache or authority.

CIM exposes creation at microsecond precision. Keep that representation while
checking the complete kernel FILETIME for stability between independent samples.
"""
from datetime import datetime, timedelta, timezone
import ctypes
from ctypes import wintypes
import hashlib
import os


def _sample():
    if os.name != 'nt':
        raise ValueError('Windows current-process evidence required')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    n=ctypes.WinDLL('ntdll',use_last_error=True)
    k.GetCurrentProcess.restype=wintypes.HANDLE
    k.GetCurrentProcessId.restype=wintypes.DWORD
    k.GetCommandLineW.restype=wintypes.LPWSTR
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    class Basic(ctypes.Structure):
        _fields_=[('reserved',ctypes.c_void_p),('peb',ctypes.c_void_p),
                  ('reserved2',ctypes.c_void_p*2),('pid',ctypes.c_size_t),('parent',ctypes.c_size_t)]
    n.NtQueryInformationProcess.argtypes=[wintypes.HANDLE,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG)]
    n.NtQueryInformationProcess.restype=wintypes.LONG
    handle=k.GetCurrentProcess();pid=k.GetCurrentProcessId()
    info=Basic();length=wintypes.ULONG()
    if n.NtQueryInformationProcess(handle,0,ctypes.byref(info),ctypes.sizeof(info),ctypes.byref(length))!=0 or length.value!=ctypes.sizeof(info):
        raise ValueError('Current native ancestry unavailable')
    image=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(image))
    times=[wintypes.FILETIME() for _ in range(4)]
    if not k.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(size)) or not k.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
        raise ValueError('Current native image or creation unavailable')
    command=k.GetCommandLineW()
    ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    if (pid!=os.getpid() or info.pid!=pid or not 0<info.parent<2**32 or
            not 0<size.value<32768 or not isinstance(command,str) or not 0<len(command)<=32768 or
            ticks<=116444736000000000):
        raise ValueError('Current native evidence incomplete')
    created=datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(microseconds=(ticks-116444736000000000)//10)
    return {'pid':pid,'parent_pid':info.parent,'creation_ticks':ticks,
            'created':created.strftime('%Y-%m-%dT%H:%M:%S.')+f'{created.microsecond:06d}0Z',
            'executable':image.value,'command_sha256':hashlib.sha256(command.encode()).hexdigest()}


def current():
    first=_sample();second=_sample()
    if first!=second:
        raise ValueError('Current native identity bracket unstable')
    from scripts.genesis_launch_provenance import descriptor
    return descriptor({k:v for k,v in second.items() if k!='creation_ticks'})
