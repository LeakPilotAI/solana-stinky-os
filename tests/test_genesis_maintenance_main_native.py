"""Native actual-main recovery proof with synthetic business workloads only."""
import hashlib
import json
import ntpath
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name!='nt',reason='Windows native process/socket witnesses required')
def test_authenticated_actual_main_native_children_sockets_and_cooperative_exit(tmp_path):
    Job=pytest.importorskip('scripts.genesis_native_descendants').OwnedDescendantJob
    from scripts.genesis_private_child_entry import native
    from scripts.genesis_launch_provenance import LaunchObservations,signed
    from scripts.genesis_child_observation import target
    from test_genesis_maintenance_binding import ticks
    root=tmp_path/'synthetic-root';(root/'scripts').mkdir(parents=True)
    (root/'post_migration').mkdir();(root/'post_migration/__init__.py').write_text('')
    (root/'docker-compose.yml').write_text('services: {}')
    (root/'GB10A-ISOLATED').write_text('synthetic-business-jobs-no-database')
    body='''import json,os,socket,time
from pathlib import Path
root=Path(os.environ['STINKY_ROOT']).resolve()
if (root/'GB10A-ISOLATED').read_text()!='synthetic-business-jobs-no-database':raise RuntimeError('No isolated root')
pid=os.getpid();s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)
try:
 (root/f'job-{pid}.json').write_text(json.dumps({'pid':pid,'port':s.getsockname()[1]}))
 deadline=time.monotonic()+45
 while not (root/f'finish-{pid}').is_file():
  if time.monotonic()>deadline:raise RuntimeError('Unresolved native socket ownership; HOLD')
  time.sleep(.02)
finally:s.close()
print('SYNTHETIC_BUSINESS_JOB_COMPLETED',flush=True)
'''
    for name in ['run_intelligence_shadow_scorer.py','run_intelligence_paper_decisions.py',
                 'run_intelligence_paper_execution_plans.py','run_intelligence_execution_v2.py']:
        (root/'scripts'/name).write_text(body)
    (root/'post_migration/cli.py').write_text(body)
    driver=ROOT/'tests/genesis_maintenance_main_fixture.py'
    driver_hash=hashlib.sha256(driver.read_bytes()).hexdigest()
    env={**os.environ,'PYTHONPATH':os.pathsep.join([str(root),str(ROOT),str(ROOT/'tests'),str(ROOT/'.venv/Lib/site-packages')]),
         'STINKY_DATABASE_URL':'invalid://GB10A_NO_DATABASE','STINKY_REDIS_URL':'redis://127.0.0.1:1/0',
         'STINKY_SOLANA_RPC_URL':'http://127.0.0.1:1'}
    env.pop('GENESIS_SUPERVISOR_LAUNCH_TOKEN',None)
    command=[sys._base_executable,str(driver),str(root)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,cwd=root,env=env)
    witness=None
    def read():
        result=queue.Queue()
        t=threading.Thread(target=lambda:result.put(proc.stdout.readline()),daemon=True);t.start()
        line=result.get(timeout=30);t.join(2);assert not t.is_alive();return line
    try:
        assert read().strip()=='PRIVATE-MAIN-READY'
        owner=native(proc.pid)
        assert owner['parent_pid']==os.getpid()
        assert ntpath.normcase(owner['executable'])==ntpath.normcase(sys._base_executable)
        assert owner['command_sha256']==hashlib.sha256(subprocess.list2cmdline(command).encode()).hexdigest()
        retained={**owner,'creation_ticks':ticks(proc.pid)}
        def verify(pid):return {**native(pid),'creation_ticks':ticks(pid)}
        witness=Job(proc,retained,verify)
        launches=LaunchObservations(native);frame=launches.prepare('maintain',owner)
        proc.stdin.write(json.dumps({'frame':frame.hex()})+'\n');proc.stdin.flush()
        proof=json.loads(read());assert launches.accept('maintain',proof)['phase']=='ATTESTED'
        private=json.loads(frame)
        ack=signed(bytes.fromhex(private['key']),{'kind':'fixture-main-processed','target':target(proof)})
        out,err=proc.communicate(json.dumps(ack)+'\n',timeout=210)
        (tmp_path/'native-main-stderr.txt').write_text(err.replace(private['key'],'[REDACTED]'))
        assert proc.returncode==0,'Native actual-main recovery failed; inspect retained isolated fixture'
        assert not err
        kernel=witness.verified_exit();assert kernel['root_exit_code']==0 and kernel['active_processes']==0
        result=json.loads((root/'native-main-proof.json').read_text())
        assert result['phase']=='QUIESCED' and result['loop_threads_retired'] and result['controller_retired']
        assert len(result['children'])==6 and len(result['sockets'])==6
        assert all(p['root_exit_code']==0 and p['active_processes']==0 for p in result['children'])
        assert all(p['verified'] is True for p in result['sockets'])
        assert hashlib.sha256(driver.read_bytes()).hexdigest()==driver_hash
        assert result['cadences']==[10,60,21600] and not result['lifecycle_authorized']
        assert (root/'logs/runtime-state-maintain.json').is_file() and (root/'logs/runtime-state.json').is_file()
        secret=private['key']
        assert all(secret not in value for value in [out,err,(root/'logs/maintain.log').read_text(),
                    (root/'logs/runtime-state-maintain.json').read_text(),json.dumps(result)])
        (tmp_path/'actual-main-certification.json').write_text(json.dumps({'kernel':kernel,'main':result,
            'real_sql_jobs':False,'redis_attribution':False,'production_certified':False},indent=2))
    finally:
        if proc.stdin and not proc.stdin.closed:proc.stdin.close()
        if proc.poll() is None:
            (tmp_path/'HOLD-main-process.json').write_text(json.dumps({'pid':proc.pid,'reason':'No forced cleanup authorized'}))
        if witness is not None:witness.close()
