from types import SimpleNamespace
import json
import pytest
from scripts import safe_genesis_start as safe

@pytest.mark.parametrize('name',list(safe.DEPENDENCIES))
def test_cold_dependency_readiness_retries_only_probes(monkeypatch,name):
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if len(calls)<3:raise RuntimeError('not yet listening')
        return 'accepting connections' if name=='stinky-postgres' else 'PONG'
    monkeypatch.setattr(safe,'run',run)
    monkeypatch.setattr(safe.time,'monotonic',lambda:0)
    monkeypatch.setattr(safe.time,'sleep',lambda delay:None)
    safe.wait_dependency_ready('docker',name,started=True)
    assert len(calls)==3
    assert all(args[1:3]==['exec',name] for args in calls)
    assert not any(set(args)&{'start','stop','restart','rm','compose','CONFIG','FLUSHALL'} for args in calls)

@pytest.mark.parametrize('name',list(safe.DEPENDENCIES))
def test_existing_dependency_failure_not_restarted_or_hidden(monkeypatch,name):
    calls=[]
    def fail(args,**kwargs):
        calls.append(args);raise RuntimeError('not ready')
    monkeypatch.setattr(safe,'run',fail)
    with pytest.raises(RuntimeError,match='not ready'):
        safe.wait_dependency_ready('docker',name,started=False)
    assert len(calls)==1

@pytest.mark.parametrize('name',list(safe.DEPENDENCIES))
def test_readiness_timeout_is_bounded_without_destructive_fallback(monkeypatch,name):
    ticks=iter([0,1,46]);calls=[]
    monkeypatch.setattr(safe.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(safe.time,'sleep',lambda delay:None)
    def fail(args,**kwargs):
        calls.append(args);raise RuntimeError('synthetic failure')
    monkeypatch.setattr(safe,'run',fail)
    with pytest.raises(RuntimeError,match='readiness timed out'):
        safe.wait_dependency_ready('docker',name,started=True)
    assert len(calls)==2
    assert all(args[1]=='exec' for args in calls)

def test_successful_command_with_wrong_postgres_or_redis_reply_is_not_ready(monkeypatch):
    monkeypatch.setattr(safe,'run',lambda *a,**k:'wrong')
    for name in ('stinky-postgres','stinky-redis'):
        with pytest.raises(RuntimeError):safe.wait_dependency_ready('docker',name)

def test_stopped_minio_started_once_and_readiness_wait_does_not_start_optional_apps(monkeypatch):
    calls=[];attempts=0
    records=[]
    for name,(service,dest,port,host) in safe.DEPENDENCIES.items():
        records.append({'Name':'/'+name,'Config':{'Labels':{'com.docker.compose.project':'project-genesis','com.docker.compose.service':service}},'State':{'Status':'exited' if name=='stinky-minio' else 'running'},'Mounts':[{'Destination':dest,'Type':'volume','Name':'project-genesis_'+service+'-data'}],'HostConfig':{'PortBindings':{port:[{'HostPort':host}]}}})
    def run(args,**kwargs):
        nonlocal attempts
        calls.append(args)
        if args[1]=='inspect':return json.dumps(records)
        if 'pg_isready' in args:return 'accepting connections'
        if 'PING' in args:return 'PONG'
        if 'curl' in args:
            attempts+=1
            if attempts==1:raise RuntimeError('could not connect')
        return ''
    monkeypatch.setattr(safe,'run',run)
    monkeypatch.setattr(safe.time,'monotonic',lambda:0)
    monkeypatch.setattr(safe.time,'sleep',lambda delay:None)
    safe.ensure_dependencies(SimpleNamespace(find_docker=lambda:'docker'))
    assert [args for args in calls if args[1]=='start']==[['docker','start','stinky-minio']]
    assert attempts==2
    assert not any(set(args)&{'stop','restart','rm','compose','XTRIM','CONFIG','FLUSHDB','FLUSHALL','atlas'} for args in calls)


def test_unknown_dependency_fails_before_probe(monkeypatch):
    monkeypatch.setattr(safe,'run',lambda *a,**k:pytest.fail('unowned probe'))
    with pytest.raises(ValueError,match='allowlisted'):
        safe.wait_dependency_ready('docker','atlas-redis',started=True)
