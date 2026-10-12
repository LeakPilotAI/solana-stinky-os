import copy,json
from types import SimpleNamespace
import pytest
from scripts.run_genesis_service import recover_watch_dependencies,WATCH_CONTAINERS
from scripts.safe_genesis_start import startup_lock
from test_safe_genesis_start import record


def records(states):
    rows=[record(name,state) for name,state in zip(WATCH_CONTAINERS,states)]
    for i,row in enumerate(rows):
        row['Id']=str(i+1)*64;row['Image']='sha256:'+'a'*64;row['Mounts'][0]['RW']=True
    return rows


def runner(rows,*,failure=False,mutation=None):
    calls=[];state=copy.deepcopy(rows)
    def run(args,**options):
        calls.append(args)
        if args[1]=='inspect':return SimpleNamespace(returncode=0,stdout=json.dumps(state))
        assert args[1]=='start' and set(args[2:])<={row['Id'] for row in state}
        if failure:return SimpleNamespace(returncode=1)
        for row in state:
            if row['Id'] in args[2:]:row['State']['Status']='running'
        if mutation:mutation(state)
        return SimpleNamespace(returncode=0)
    return run,calls


@pytest.mark.parametrize('states',[['running']*3,['running','exited','running'],['exited']*3])
def test_only_exact_owned_stopped_ids_start_and_repeat_is_noop(tmp_path,states):
    rows=records(states);run,calls=runner(rows)
    expected=[r['Id'] for r in rows if r['State']['Status']!='running']
    assert recover_watch_dependencies(tmp_path,'docker',run)==expected
    assert recover_watch_dependencies(tmp_path,'docker',run)==[]
    starts=[c for c in calls if c[1]=='start']
    assert starts==([['docker','start',*expected]] if expected else [])
    assert not any(set(c)&{'stop','restart','rm','compose','prune','CONFIG','XTRIM','FLUSHDB','FLUSHALL','atlas'} for c in calls)


@pytest.mark.parametrize('bad',['project','volume','port','missing','duplicate','image','id','readonly','extra_mount'])
def test_ambiguous_dependency_ownership_never_starts_anything(tmp_path,bad):
    rows=records(['exited']*3)
    if bad=='project':rows[0]['Config']['Labels']['com.docker.compose.project']='atlas'
    if bad=='volume':rows[1]['Mounts'][0]['Name']='atlas-redis-data'
    if bad=='port':rows[1]['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='6379'
    if bad=='missing':rows.pop()
    if bad=='duplicate':rows[2]=copy.deepcopy(rows[1])
    if bad=='image':rows[1]['Image']='unknown'
    if bad=='id':rows[1]['Id']='stale'
    if bad=='readonly':rows[1]['Mounts'][0]['RW']=False
    if bad=='extra_mount':rows[1]['Mounts'].append({'Name':'atlas-data','RW':True})
    run,calls=runner(rows)
    with pytest.raises(RuntimeError):recover_watch_dependencies(tmp_path,'docker',run)
    assert not [c for c in calls if c[1]=='start']


def test_concurrent_start_stop_lock_prevents_watchdog_dependency_recovery(tmp_path):
    run,calls=runner(records(['exited']*3))
    with startup_lock(tmp_path/'logs/application-start.lock'):
        with pytest.raises(OSError):recover_watch_dependencies(tmp_path,'docker',run)
    assert calls==[]


@pytest.mark.parametrize('failure',[None,'refused','corrupt','too_large'])
def test_engine_disconnection_has_no_destructive_fallback(tmp_path,failure):
    calls=[]
    def run(args,**kw):
        calls.append(args)
        if failure is None:return None
        return SimpleNamespace(returncode=1 if failure=='refused' else 0,
            stdout='{' if failure=='corrupt' else 'x'*(1024*1024+1))
    with pytest.raises((RuntimeError,ValueError)):recover_watch_dependencies(tmp_path,'docker',run)
    assert len(calls)==1 and calls[0][1]=='inspect'


@pytest.mark.parametrize('bad',['failed_start','changed_mount','still_stopped','changed_id'])
def test_successful_command_cannot_substitute_for_preserved_running_identity(tmp_path,bad):
    def mutate(rows):
        if bad=='changed_mount':rows[1]['Mounts'][0]['Name']='atlas-data'
        if bad=='still_stopped':rows[1]['State']['Status']='exited'
        if bad=='changed_id':rows[1]['Id']='9'*64
    run,calls=runner(records(['running','exited','running']),failure=bad=='failed_start',mutation=mutate)
    with pytest.raises(RuntimeError):recover_watch_dependencies(tmp_path,'docker',run)
    assert len([c for c in calls if c[1]=='start'])==1
