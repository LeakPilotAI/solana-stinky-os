"""Actual PowerShell status with isolated native/Docker fixture surfaces only."""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
SHELL=shutil.which('powershell.exe')
pytestmark=pytest.mark.skipif(not SHELL,reason='Windows PowerShell required')


@pytest.mark.parametrize('case',[
    'stopped','docker_offline','bad_json','multiple_records','foreign_project',
    'foreign_volume','foreign_port','extra_binding','readonly_data','extra_writable',
    'inventory_failure','verified','duplicate','command_redaction',
    'mixed_case','wrong_executable','extra_arguments','reused_pid','stale_heartbeat',
    'missing_creation','foreign_runner',
])
def test_read_only_status_reports_fail_closed_without_secret_or_lifecycle_authority(tmp_path,case):
    root=tmp_path/'isolated-repository';scripts=root/'scripts/windows';scripts.mkdir(parents=True)
    for name in ('Genesis-Background-Status.ps1','Genesis-Heartbeat-Verify.ps1'):
        shutil.copyfile(ROOT/'scripts/windows'/name,scripts/name)
    (root/'logs').mkdir()
    now=datetime.now(timezone.utc).isoformat()
    containers={}
    specs=[('stinky-postgres','postgres','/var/lib/postgresql/data','5432/tcp','5433'),
        ('stinky-redis','redis','/data','6379/tcp','6380'),('stinky-minio','minio','/data','9000/tcp','9010')]
    for name,service,destination,port,host in specs:
        containers[name]={'Id':'a'*64,'Name':'/'+name,'Config':{'Labels':{
            'com.docker.compose.project':'project-genesis','com.docker.compose.service':service,
            'com.docker.compose.project.working_dir':str(root),
            'com.docker.compose.project.config_files':str(root/'docker-compose.yml')}},
            'Mounts':[{'Type':'volume','Name':f'project-genesis_{service}-data','Destination':destination,'RW':True}],
            'HostConfig':{'PortBindings':{port:[{'HostPort':host,'HostIp':'127.0.0.1'}]}},'State':{'Status':'exited'}}
    redis=containers['stinky-redis']
    if case=='foreign_project':redis['Config']['Labels']['com.docker.compose.project']='atlas'
    if case=='foreign_volume':redis['Mounts'][0]['Name']='atlas_redis-data'
    if case=='foreign_port':redis['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='9999'
    if case=='extra_binding':redis['HostConfig']['PortBindings']['6379/tcp'].append({'HostPort':'9999'})
    if case=='readonly_data':redis['Mounts'][0]['RW']=False
    if case=='extra_writable':redis['Mounts'].append({'Type':'bind','Source':'other','Destination':'/other','RW':True})
    processes=[]
    identity_cases=('verified','command_redaction','mixed_case','wrong_executable',
        'extra_arguments','reused_pid','stale_heartbeat','missing_creation','foreign_runner')
    for pid in ([42,43] if case=='duplicate' else [42] if case in identity_cases else []):
        executable=str(root/'.venv/Scripts/pythonw.exe')
        cmd=f'"{executable}" "{root}/scripts/run_genesis_service.py" --name api'.replace('/','\\')
        if case=='command_redaction':cmd=f'python.exe -c "{root}\\ SECRET_COMMAND_CANARY"'
        if case=='mixed_case':cmd=cmd.split(' --name ')[0].upper()+' --name api';executable=executable.upper()
        if case=='wrong_executable':executable=str(root/'other/pythonw.exe')
        if case=='extra_arguments':cmd+=' --unexpected-option'
        if case=='foreign_runner':cmd=cmd.replace('run_genesis_service.py','other_runner.py')
        processes.append({'ProcessId':pid,'ParentProcessId':10,'Name':'pythonw.exe',
            'ExecutablePath':executable,'CommandLine':cmd,'CreationDate':now})
    heartbeat={'service':'api','supervisor_pid':42,
        'supervisor_phase':'RUNNING','supervisor_started_at':now,'as_of':now}
    if case=='reused_pid':heartbeat['supervisor_started_at']='2000-01-01T00:00:00Z'
    if case=='stale_heartbeat':heartbeat['as_of']='2000-01-01T00:00:00Z'
    if case=='missing_creation':processes[0]['CreationDate']=None
    (root/'logs/runtime-state-api.json').write_text(json.dumps(heartbeat))
    fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps({'case':case,'containers':containers,'processes':processes}))
    harness=tmp_path/'harness.ps1'
    harness.write_text("""param($Fixture,$Status)
$global:fixtureData=Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$global:calls=New-Object System.Collections.Generic.List[string]
function global:Get-CimInstance {
 if ($global:fixtureData.case -eq 'inventory_failure') { throw 'NATIVE_SECRET_CANARY' }
 foreach ($row in $global:fixtureData.processes) {
  if ($null -ne $row.CreationDate) { $row.CreationDate=[datetimeoffset]::Parse($row.CreationDate).UtcDateTime }
  $row
 }
}
function global:docker {
 if ($args[0] -cne 'inspect' -or $args[1] -cnotin @('stinky-postgres','stinky-redis','stinky-minio')) { throw 'NON_READ_ONLY_COMMAND' }
 $global:calls.Add([string]$args[1]);$global:LASTEXITCODE=0
 if ($global:fixtureData.case -eq 'docker_offline') { throw 'DOCKER_SECRET_CANARY' }
 if ($global:fixtureData.case -eq 'bad_json') { return '{malformed DOCKER_SECRET_CANARY}' }
 $record=$global:fixtureData.containers.PSObject.Properties[$args[1]].Value
 if ($global:fixtureData.case -eq 'multiple_records') { ConvertTo-Json -InputObject @($record,$record) -Depth 12 -Compress }
 else { ConvertTo-Json -InputObject @($record) -Depth 12 -Compress }
}
$result=& $Status -Json | ConvertFrom-Json
@{result=$result;calls=@($global:calls.ToArray())} | ConvertTo-Json -Depth 14 -Compress
""",encoding='utf-8')
    result=subprocess.run([SHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(harness),
        '-Fixture',str(fixture),'-Status',str(scripts/'Genesis-Background-Status.ps1')],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert '_CANARY' not in result.stdout
    data=json.loads(result.stdout);status=data['result']
    assert data['calls']==['stinky-postgres','stinky-redis','stinky-minio']
    assert not any(status['lifecycle_actions'][name] for name in
        ('start_authorized','stop_authorized','restart_authorized','gaming_mode_authorized'))
    if case=='stopped':assert status['state']=='STOPPED'
    elif case in (*identity_cases,'duplicate'):
        assert status['state']=='AMBIGUOUS'
        if case in ('verified','mixed_case'):
            assert status['processes'][0]['classification']=='SUPERVISOR_VERIFIED'
            assert status['processes'][0]['created'].endswith('Z')
            assert status['processes'][0]['heartbeat_reason']=='HEARTBEAT_MATCH'
        if case=='duplicate':assert status['duplicate_supervisors'][0]['count']==2
        if case=='command_redaction':assert 'command_line' not in status['processes'][0]
        if case in ('wrong_executable','extra_arguments','foreign_runner'):
            assert status['processes'][0]['classification']=='UNVERIFIED'
        if case in ('reused_pid','stale_heartbeat','missing_creation'):
            assert status['processes'][0]['classification']=='SUPERVISOR_CANDIDATE'
    else:assert status['state']=='ERROR'
