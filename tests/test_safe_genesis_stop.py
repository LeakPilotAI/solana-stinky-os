import subprocess
from types import SimpleNamespace
from pathlib import Path
import pytest
from scripts import safe_genesis_start as start, safe_genesis_stop as stop

@pytest.mark.parametrize('code,stderr',[(1,'password=secret TOKEN=secret https://user:secret@host/x?key=secret connection refused'),(127,'executable not found')])
def test_probe_failure_identifies_command_exit_without_credentials(monkeypatch,code,stderr):
 monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code,stdout='',stderr=stderr))
 with pytest.raises(RuntimeError) as e:start.run(['docker','exec','stinky-postgres','psql'],input='secret')
 assert f'exit={code}' in str(e.value) and 'psql' in str(e.value)
 assert 'secret' not in str(e.value) and 'https:' not in str(e.value)

def test_probe_timeout_no_secret_output(monkeypatch):
 def timeout(*a,**k):raise subprocess.TimeoutExpired(a[0],15,stderr='secret')
 monkeypatch.setattr(subprocess,'run',timeout)
 with pytest.raises(RuntimeError,match='timeout=15s') as e:start.run(['docker','inspect'])
 assert 'secret' not in str(e.value)

def rows(root,name='collector'):
 return [(10,0,'python.exe',f'"{root}/.venv/Scripts/python.exe" "{root}/scripts/run_genesis_service.py" --name {name}'),
         (11,10,'python.exe',f'python.exe -m {start.MODULES[name]}'),
         (90,0,'python.exe','python.exe -m atlas.api'),
         (91,90,'node.exe','node.exe D:/Work/Project-Atlas/web.js')]

def test_shutdown_exact_owned_tree_atlas_untouched(tmp_path):
 assert stop.stop_plan(SimpleNamespace(ROOT=tmp_path),rows(tmp_path))==[10,11]

def test_shutdown_absent_services_ignores_stale_pid_and_atlas(tmp_path):
 (tmp_path/'stinky-pids.txt').write_text('collector=90')
 assert stop.stop_plan(SimpleNamespace(ROOT=tmp_path),rows(tmp_path)[2:])==[]

def test_foreign_runner_fails_before_termination(tmp_path):
 r=rows(tmp_path);r[0]=(10,0,'python.exe',f'python.exe "{tmp_path}-atlas/scripts/run_genesis_service.py" --name collector')
 with pytest.raises(RuntimeError,match='repository ownership'):stop.stop_plan(SimpleNamespace(ROOT=tmp_path),r)

def test_foreign_descendant_fails_closed(tmp_path):
 r=rows(tmp_path)+[(12,10,'python.exe','python.exe -m atlas.api')]
 with pytest.raises(RuntimeError,match='Unverified'):stop.stop_plan(SimpleNamespace(ROOT=tmp_path),r)

def test_shutdown_creation_reuse_never_kills_reused_pid(tmp_path,monkeypatch):
 from scripts import start_paper_runtime as paper
 l=SimpleNamespace(ROOT=tmp_path,LOG_DIR=tmp_path/'logs')
 monkeypatch.setattr(start,'inventory',lambda _:rows(tmp_path))
 calls=[];counts={}
 def identity(p):
  counts[p]=counts.get(p,0)+1
  return counts[p]
 monkeypatch.setattr(paper,'_windows_process_started_at',identity)
 monkeypatch.setattr(subprocess,'run',lambda *a,**k:calls.append(a))
 with pytest.raises(RuntimeError,match='identity changed'):stop.stop(l)
 assert calls==[]

def test_shutdown_only_individual_verified_pids_no_docker(tmp_path,monkeypatch):
 from scripts import start_paper_runtime as paper
 l=SimpleNamespace(ROOT=tmp_path,LOG_DIR=tmp_path/'logs',listen_pid=lambda _:0);active=rows(tmp_path);calls=[]
 monkeypatch.setattr(start,'inventory',lambda _:list(active))
 monkeypatch.setattr(paper,'_windows_process_started_at',lambda p:123 if any(r[0]==p for r in active) else None)
 def terminate(args,**kw):
  calls.append(args);active[:]=[r for r in active if r[0]!=int(args[2])]
  return SimpleNamespace(returncode=0)
 monkeypatch.setattr(subprocess,'run',terminate)
 assert stop.stop(l)==[10,11]
 assert calls==[['taskkill','/PID','10','/F'],['taskkill','/PID','11','/F']]
 assert [r[0] for r in active]==[90,91]
 assert stop.stop(l)==[]

def test_owned_windows_console_host_exact_system_path_only(tmp_path,monkeypatch):
 monkeypatch.setenv('SystemRoot','C:/Windows')
 l=SimpleNamespace(ROOT=tmp_path)
 r=rows(tmp_path)+[(12,11,'conhost.exe',r'"\??\C:\Windows\System32\conhost.exe" 0x4')]
 assert stop.stop_plan(l,r)==[10,11,12]
 r[-1]=(12,11,'conhost.exe','C:/Work/Project-Atlas/conhost.exe 0x4')
 with pytest.raises(RuntimeError,match='Unverified'):stop.stop_plan(l,r)
