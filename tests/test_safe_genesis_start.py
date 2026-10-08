from argparse import Namespace
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime,timezone
import json
import pytest
from scripts import safe_genesis_start as safe

@pytest.fixture
def launcher(tmp_path,monkeypatch):
 (tmp_path/'.env').write_text('fixture');logs=tmp_path/'logs';logs.mkdir()
 calls=[];active={n:100+i for i,n in enumerate(safe.SERVICES)}
 l=SimpleNamespace(ROOT=tmp_path,LOG_DIR=logs,HEALTH={},ensure_docker=lambda:calls.append('dependencies'),apply_schema=lambda:calls.append('schema'),write_pid_file=lambda p:calls.append(('pids',p)),http_ok=lambda *a:True,open_operator=lambda:calls.append('browser'),say=lambda *a:None,fail=lambda *a,**k:calls.append('failure'))
 def start(name,**k):
  if name not in active:active[name]=200+len(active);calls.append(name)
  return active[name]
 l.start_detached=start
 return l,calls,active

@pytest.mark.parametrize('missing',[None,'web','api','collector','maintain'])
def test_repeated_recovery_only_starts_missing(launcher,missing):
 l,calls,active=launcher
 if missing:active.pop(missing)
 args=Namespace(sync=False,restart=False,skip_sync=True)
 assert safe.recover(l,args)==0;assert safe.recover(l,args)==0
 assert [x for x in calls if x in safe.SERVICES]==([missing] if missing else [])
 assert calls.index('schema')<next(i for i,x in enumerate(calls) if isinstance(x,tuple))

@pytest.mark.parametrize('flag',['sync','restart'])
def test_unsafe_flags_fail_before_any_probe(launcher,flag):
 l,calls,_=launcher;args=Namespace(sync=False,restart=False);setattr(args,flag,True)
 assert safe.recover(l,args)==1;assert calls==['failure']

def test_dependency_failure_starts_no_application(launcher):
 l,calls,_=launcher
 def fail():raise RuntimeError('unavailable')
 l.ensure_docker=fail
 assert safe.recover(l,Namespace(sync=False,restart=False))==1;assert calls==['failure']

def record(name,state='running'):
 service,dest,port,host=safe.DEPENDENCIES[name]
 return {'Name':'/'+name,'Config':{'Labels':{'com.docker.compose.project':'project-genesis','com.docker.compose.service':service}},'State':{'Status':state},'Mounts':[{'Destination':dest,'Type':'volume','Name':f'project-genesis_{service}-data'}],'HostConfig':{'PortBindings':{port:[{'HostPort':host}]}}}

@pytest.mark.parametrize('stopped',[False,True])
def test_dependencies_preserved_no_redis_mutation(monkeypatch,stopped):
 calls=[]
 def run(args,**k):
  calls.append(args)
  if args[1]=='inspect':return json.dumps([record(n,'exited' if stopped and n=='stinky-redis' else 'running') for n in safe.DEPENDENCIES])
  if 'pg_isready' in args:return 'accepting connections'
  if 'PING' in args:return 'PONG\n'
  return ''
 monkeypatch.setattr(safe,'run',run);safe.ensure_dependencies(SimpleNamespace(find_docker=lambda:'docker'))
 assert [c for c in calls if c[1]=='start']==([['docker','start','stinky-redis']] if stopped else [])
 assert all(not set(c)&{'stop','rm','restart','compose','XTRIM','CONFIG','atlas'} for c in calls)

@pytest.mark.parametrize('bad',['project','volume','port'])
def test_dependency_ownership_fails_closed_before_start(monkeypatch,bad):
 rows=[record(n,'exited') for n in safe.DEPENDENCIES];r=rows[0]
 if bad=='project':r['Config']['Labels']['com.docker.compose.project']='atlas'
 elif bad=='volume':r['Mounts'][0]['Name']='atlas-data'
 else:r['HostConfig']['PortBindings']['5432/tcp'][0]['HostPort']='5432'
 calls=[]
 monkeypatch.setattr(safe,'run',lambda a,**k:(calls.append(a) or json.dumps(rows)))
 with pytest.raises(RuntimeError):safe.ensure_dependencies(SimpleNamespace(find_docker=lambda:'docker'))
 assert len(calls)==1

def test_startup_lock_serializes_shortcut_launches(tmp_path):
 p=tmp_path/'lock'
 with safe.startup_lock(p):
  with pytest.raises(OSError):
   with safe.startup_lock(p):pytest.fail('concurrent launch acquired lock')
 with safe.startup_lock(p):pass

def test_native_inventory_failure_never_starts(launcher):
 l,_,_=launcher;l.list_win_processes=lambda:[]
 with pytest.raises(RuntimeError):safe.recover_service(l,'collector')

def test_stale_pid_file_does_not_prove_health(launcher):
 l,_,_=launcher;(l.LOG_DIR/'stinky-pids.txt').write_text('collector=999\n')
 assert safe.service_pid(l,'collector',[(999,0,'other.exe','unrelated')]) is None

def test_duplicate_chains_fail_closed(launcher):
 l,_,_=launcher;cmd=f'python.exe "{l.ROOT}/scripts/run_genesis_service.py" --name collector'
 with pytest.raises(RuntimeError,match='Multiple'):safe.service_pid(l,'collector',[(1,0,'python.exe',cmd),(2,0,'python.exe',cmd)])

def test_owned_wrapper_is_single_chain_and_stale_heartbeat_blocks(launcher,monkeypatch):
 from scripts import start_paper_runtime as paper
 l,_,_=launcher;now=datetime.now(timezone.utc);cmd=f'python.exe "{l.ROOT}/scripts/run_genesis_service.py" --name collector'
 rows=[(1,0,'python.exe',cmd),(2,1,'python.exe',cmd),(3,2,'python.exe','python -m post_migration.cli')]
 monkeypatch.setattr(paper,'_windows_process_started_at',lambda pid:now)
 p=l.LOG_DIR/'runtime-state-collector.json';state={'service':'collector','supervisor_pid':2,'supervisor_started_at':now.isoformat(),'as_of':now.isoformat(),'supervisor_phase':'SUPERVISING'};p.write_text(json.dumps(state))
 assert safe.service_pid(l,'collector',rows)==2
 with pytest.raises(RuntimeError,match='child unavailable'):safe.service_pid(l,'collector',rows[:2])
 state['as_of']='2000-01-01T00:00:00+00:00';p.write_text(json.dumps(state))
 with pytest.raises(RuntimeError):safe.service_pid(l,'collector',rows)

def test_orphan_or_foreign_port_not_killed(launcher):
 l,_,_=launcher;l.listen_pid=lambda p:123
 with pytest.raises(RuntimeError):safe.reject_orphan(l,'web',[])
 with pytest.raises(RuntimeError):safe.reject_orphan(l,'collector',[(123,0,'python.exe','python -m post_migration.cli')])

def test_new_start_is_detached_token_verified_and_preserves_logs(launcher,monkeypatch):
 l,_,_=launcher
 (l.ROOT/'.venv/Scripts').mkdir(parents=True);(l.ROOT/'.venv/Scripts/python.exe').write_text('fixture')
 (l.ROOT/'scripts').mkdir();(l.ROOT/'scripts/run_genesis_service.py').write_text('fixture')
 (l.LOG_DIR/'collector.log').write_text('historical evidence\n')
 l.list_win_processes=lambda:[(1,0,'other.exe','fixture')];l.listen_pid=lambda port:0
 calls=[]
 class Child:
  def poll(self):return None
 def spawn(args,**kwargs):
  calls.append((args,kwargs))
  (l.LOG_DIR/'runtime-state-collector.json').write_text(json.dumps({'supervisor_launch_token':kwargs['env']['GENESIS_SUPERVISOR_LAUNCH_TOKEN']}))
  return Child()
 monkeypatch.setattr(safe.subprocess,'Popen',spawn)
 monkeypatch.setattr(safe,'service_pid',lambda *args:55 if calls else None)
 assert safe.recover_service(l,'collector')==55
 assert len(calls)==1 and calls[0][0][-2:]==['--name','collector']
 assert calls[0][1]['stdin']==safe.subprocess.DEVNULL
 assert calls[0][1]['env']['GENESIS_SUPERVISOR_LAUNCH_TOKEN']
 assert (l.LOG_DIR/'collector.log').read_text()=='historical evidence\n'
 assert not (l.LOG_DIR/'collector.log.old').exists()

@pytest.mark.parametrize('status',[200,404,500])
def test_http_health_requires_actual_200(monkeypatch,status):
 import start_genesis as l
 class Response:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def __init__(self):self.status=status
 monkeypatch.setattr(l.urllib.request,'urlopen',lambda *a,**k:Response())
 assert l.http_ok('http://fixture') is (status==200)

def test_missing_dependency_never_creates_container(monkeypatch):
 calls=[]
 monkeypatch.setattr(safe,'run',lambda a,**k:(calls.append(a) or '[]'))
 with pytest.raises(RuntimeError):safe.ensure_dependencies(SimpleNamespace(find_docker=lambda:'docker'))
 assert len(calls)==1 and calls[0][1]=='inspect'

@pytest.mark.parametrize('full',[False,True])
def test_absent_paper_services_only_started_by_explicit_full(launcher,full):
 l,calls,active=launcher
 for name in safe.PAPER_SERVICES:active.pop(name)
 args=Namespace(sync=False,restart=False,full=full,core_only=not full)
 assert safe.recover(l,args)==0;assert safe.recover(l,args)==0
 started=[x for x in calls if x in safe.SERVICES]
 assert started==(list(safe.PAPER_SERVICES) if full else [])
 assert all(n in active for n in safe.CORE_SERVICES)

@pytest.mark.parametrize('argv,expected',[([],safe.CORE_SERVICES),(['--core-only'],safe.CORE_SERVICES),(['--skip-sync'],safe.CORE_SERVICES),(['--full'],safe.SERVICES),(['--full-startup'],safe.SERVICES)])
def test_cli_profile_selection_without_running_startup(monkeypatch,argv,expected):
 import start_genesis as l
 import sys
 monkeypatch.setattr(sys,'argv',['start_genesis.py',*argv])
 monkeypatch.setattr(l,'configure_stdio',lambda:None);monkeypatch.setattr(l,'restore_search_path',lambda:None)
 def recover(launcher,args):
  assert safe.selected_services(args)==expected
  return 0
 monkeypatch.setattr(safe,'recover',recover)
 assert l.main()==0

def test_profile_conflict_fails_before_probe(launcher):
 l,calls,_=launcher
 assert safe.recover(l,Namespace(sync=False,restart=False,core_only=True,full=True))==1
 assert calls==['failure']

def test_core_metadata_preserves_separately_managed_paper_pids(tmp_path,monkeypatch):
 import start_genesis as l
 p=tmp_path/'pids';p.write_text('paper-runtime=123\ncollector=456\n')
 monkeypatch.setattr(l,'PID_FILE',p)
 l.write_pid_file({'collector':789})
 assert p.read_text()=='paper-runtime=123\ncollector=789\n'

def test_desktop_default_core_explicit_full_passes_through():
 root=Path(__file__).resolve().parents[1];cmd=(root/'Start-Stinky-OS.cmd').read_text()
 assert 'if "%~1"==""' in cmd
 assert '"%~dp0start_genesis.py" --core-only' in cmd
 assert '"%~dp0start_genesis.py" %*' in cmd
 assert 'start_paper_runtime.py' not in cmd

@pytest.mark.parametrize('filename',['run_genesis_service.py','RUN_GENESIS_SERVICE.PY','Run_Genesis_Service.Py'])
@pytest.mark.parametrize('mixed_path',[False,True])
@pytest.mark.parametrize('service',['collector','COLLECTOR'])
def test_case_variant_supervisor_is_recognized_but_not_ready_without_child(launcher,monkeypatch,filename,mixed_path,service):
 from scripts import start_paper_runtime as paper
 l,_,_=launcher;now=datetime.now(timezone.utc)
 root=str(l.ROOT).upper() if mixed_path else str(l.ROOT)
 cmd=f'"{root}/.venv/Scripts/PYTHON.EXE" "{root}/scripts/{filename}" --name {service}'
 rows=[(123,0,'PYTHON.EXE',cmd)]
 monkeypatch.setattr(paper,'_windows_process_started_at',lambda pid:now)
 state={'service':'collector','supervisor_pid':123,'supervisor_started_at':now.isoformat(),'as_of':now.isoformat(),'supervisor_phase':'SUPERVISING'}
 (l.LOG_DIR/'runtime-state-collector.json').write_text(json.dumps(state))
 l.list_win_processes=lambda:rows;l.listen_pid=lambda port:0
 attempts=[];monkeypatch.setattr(safe.subprocess,'Popen',lambda *a,**k:attempts.append(a))
 with pytest.raises(RuntimeError,match='child unavailable'):safe.recover_service(l,'collector')
 assert attempts==[]
 rows.append((124,123,'Python.Exe','python.exe -m POST_MIGRATION.CLI'))
 assert safe.service_pid(l,'collector',rows)==123

@pytest.mark.parametrize('command',[
 'python.exe -c "run_genesis_service.py --name collector"',
 'python.exe my_run_genesis_service.py --name collector',
 'python.exe run_genesis_service.py.backup --name collector',
 'python.exe run_genesis_service.py --name collector-helper',
 'node.exe run_genesis_service.py --name collector',
])
def test_similar_unrelated_commands_not_claimed(launcher,command):
 l,_,_=launcher
 assert safe.service_pid(l,'collector',[(123,0,'node.exe' if command.startswith('node') else 'python.exe',command)]) is None

@pytest.mark.parametrize('command_suffix',['--name collector --name collector','--name collector --name entities','--name=collector --name=collector'])
def test_ambiguous_service_identity_blocks_duplicate(launcher,command_suffix):
 l,_,_=launcher;cmd=f'python.exe "{l.ROOT}/scripts/RUN_GENESIS_SERVICE.PY" {command_suffix}'
 with pytest.raises(RuntimeError,match='Ambiguous'):safe.service_pid(l,'collector',[(123,0,'python.exe',cmd)])

def test_foreign_repository_path_cannot_be_proven_by_parent(launcher):
 l,_,_=launcher;own=f'python.exe "{l.ROOT}/scripts/run_genesis_service.py" --name collector';foreign=f'python.exe "{l.ROOT}-other/scripts/RUN_GENESIS_SERVICE.PY" --name collector'
 with pytest.raises(RuntimeError,match='repository ownership'):safe.service_pid(l,'collector',[(123,0,'python.exe',own),(124,123,'python.exe',foreign)])

def test_case_variant_orphan_module_blocks_without_substring_claims(launcher):
 l,_,_=launcher;l.listen_pid=lambda port:0
 with pytest.raises(RuntimeError,match='orphan'):safe.reject_orphan(l,'collector',[(123,0,'Python.Exe','python.exe -m POST_MIGRATION.CLI')])
 safe.reject_orphan(l,'collector',[(123,0,'python.exe','python.exe -c "post_migration.cli"')])
 safe.reject_orphan(l,'collector',[(123,0,'python.exe','python.exe -m post_migration.cli_backup')])

def test_case_variant_duplicate_chains_fail_closed(launcher):
 l,_,_=launcher;cmd=f'python.exe "{l.ROOT}/scripts/RUN_GENESIS_SERVICE.PY" --name=COLLECTOR'
 with pytest.raises(RuntimeError,match='Multiple'):safe.service_pid(l,'collector',[(123,0,'python.exe',cmd),(124,0,'PYTHON.EXE',cmd.lower())])

@pytest.mark.parametrize('command',['','other.exe scripts/run_genesis_service.py --name collector','python.exe "scripts/run_genesis_service.py --name collector'])
def test_unavailable_or_ambiguous_executable_identity_fails_closed(launcher,command):
 l,_,_=launcher
 with pytest.raises(RuntimeError):safe.service_pid(l,'collector',[(123,0,'python.exe',command)])
