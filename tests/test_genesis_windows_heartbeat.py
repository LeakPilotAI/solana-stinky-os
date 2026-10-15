"""Run the actual bounded PowerShell reader in isolated temporary repositories."""
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SOURCE=Path(__file__).resolve().parents[1]/'scripts/windows/Genesis-Heartbeat-Verify.ps1'
SHELL=shutil.which('powershell.exe')
pytestmark=pytest.mark.skipif(not SHELL,reason='Windows PowerShell required for actual reader certification')


def invoke(root, created):
    result=subprocess.run([SHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        str(root/'scripts/windows'/SOURCE.name),'-Service','api','-ProcessId','42',
        '-ProcessCreated',created],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('case,expected',[
    ('utf8','HEARTBEAT_MATCH'),('bom','HEARTBEAT_MATCH'),
    ('oversized','HEARTBEAT_TOO_LARGE'),('invalid_utf8',None),
    ('exact_limit','HEARTBEAT_MATCH'),('bom_exact_limit','HEARTBEAT_MATCH'),
    ('bom_over_limit','HEARTBEAT_TOO_LARGE'),('missing','HEARTBEAT_MISSING'),
    ('pid','PID_MISMATCH'),('reuse','CREATION_TIME_MISMATCH'),
    ('service','SERVICE_MISMATCH'),('phase','INVALID_PHASE'),
    ('start_naive','START_TIMEZONE_MISSING'),('creation_naive','CREATION_TIMEZONE_MISSING'),
    ('asof_naive','AS_OF_TIMEZONE_MISSING'),('stale','STALE_HEARTBEAT'),
    ('future','STALE_HEARTBEAT'),('offset','HEARTBEAT_MATCH'),('malformed',None),
    ('pid_fractional','PID_MISMATCH'),('pid_string','PID_MISMATCH'),
    ('pid_null','PID_MISMATCH'),
])
def test_actual_reader_bounds_encoding_identity_and_timestamps(tmp_path,case,expected):
    root=tmp_path/'isolated-repository';script=root/'scripts/windows'/SOURCE.name
    script.parent.mkdir(parents=True);shutil.copyfile(SOURCE,script)
    assert script.read_bytes()==SOURCE.read_bytes()
    path=root/'logs/runtime-state-api.json';path.parent.mkdir()
    now=datetime.now(timezone.utc);started=now-timedelta(seconds=1)
    created=started.isoformat()
    body={'service':'api','supervisor_pid':42,'supervisor_phase':'RUNNING',
        'supervisor_started_at':created,'as_of':now.isoformat()}
    if case=='pid':body['supervisor_pid']=43
    if case=='pid_fractional':body['supervisor_pid']=42.4
    if case=='pid_string':body['supervisor_pid']='42'
    if case=='pid_null':body['supervisor_pid']=None
    if case=='reuse':created=(started-timedelta(seconds=60)).isoformat()
    if case=='service':body['service']='collector'
    if case=='phase':body['supervisor_phase']='FAILED'
    if case=='start_naive':body['supervisor_started_at']=started.replace(tzinfo=None).isoformat()
    if case=='creation_naive':created=started.replace(tzinfo=None).isoformat()
    if case=='asof_naive':body['as_of']=now.replace(tzinfo=None).isoformat()
    if case=='stale':body['as_of']=(now-timedelta(seconds=300)).isoformat()
    if case=='future':body['as_of']=(now+timedelta(seconds=60)).isoformat()
    if case=='offset':
        body['as_of']=now.astimezone(timezone(timedelta(hours=-5))).isoformat()
        body['supervisor_started_at']=started.astimezone(timezone(timedelta(hours=-5))).isoformat()
    raw=json.dumps(body).encode('utf-8')
    if case in ('bom','bom_exact_limit','bom_over_limit'):raw=b'\xef\xbb\xbf'+raw
    if case in ('exact_limit','bom_exact_limit'):raw+=b' '*(16384-len(raw))
    if case in ('oversized','bom_over_limit'):raw+=b' '*(16385-len(raw))
    if case=='invalid_utf8':raw+=b'\xff'
    if case=='malformed':raw=b'{not-json SECRET_HB_CANARY}'
    if case!='missing':path.write_bytes(raw)
    result=invoke(root,created)
    assert 'SECRET_HB_CANARY' not in json.dumps(result)
    assert result['verified'] is (expected=='HEARTBEAT_MATCH')
    if expected is not None:assert result['reason']==expected


@pytest.mark.parametrize('invalid',[False,True])
def test_reader_disposes_handle_inside_same_powershell_process(tmp_path,invalid):
    root=tmp_path/'isolated-repository';script=root/'scripts/windows'/SOURCE.name
    script.parent.mkdir(parents=True);shutil.copyfile(SOURCE,script)
    path=root/'logs/runtime-state-api.json';path.parent.mkdir()
    now=datetime.now(timezone.utc).isoformat()
    raw=json.dumps({'service':'api','supervisor_pid':42,'supervisor_phase':'RUNNING',
        'supervisor_started_at':now,'as_of':now}).encode()
    path.write_bytes(raw+(b'\xff' if invalid else b''))
    # All paths are pytest-owned literals. No production heartbeat is accessed.
    ps="& '"+str(script).replace("'","''")+"' -Service api -ProcessId 42 -ProcessCreated '"+now+"' | Out-Null; "
    ps+="$s=[IO.File]::Open('"+str(path).replace("'","''")+"',[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); $s.Dispose(); 'DISPOSED'"
    result=subprocess.run([SHELL,'-NoProfile','-NonInteractive','-Command',ps],capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and result.stdout.strip()=='DISPOSED',result.stderr
