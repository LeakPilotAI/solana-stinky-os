import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS
from scripts.genesis_maintenance_supervision import MaintenanceDrain,classify_transaction,PERIODS
from scripts.genesis_launch_provenance import LaunchObservations,answer_launch


def controller(tmp_path):
    owner={'pid':1,'parent_pid':0,'created':'2026-10-15T00:00:00+00:00','executable':'fixture','command_sha256':'a'*64}
    launch=LaunchObservations(lambda pid:dict(owner),now=lambda:1)
    raw=launch.prepare('maintain',owner);launch.accept('maintain',answer_launch(raw,owner,now=lambda:1))
    src=tmp_path/'job.py';src.write_text('pass');cmd=(str(Path(__file__).resolve()),str(src))
    def retired(p,w):return {'root_pid':p.pid,'root_exit_code':0,'active_descendants':0,'identity_verified':True,'job_id':w['job_id'],'source_sha256':w['sha256']}
    m=MaintenanceObservation(launches=launch,native=lambda pid:owner,ancestry=lambda c,p:True,manifest={n:[(cmd,src)] for n in LOOPS},retirement=retired)
    clock=[0.0]
    d=MaintenanceDrain(m,isolated=True,idle=lambda:{'active_children':0,'unresolved_jobs':0,'admission_closed':True},clock=lambda:clock[0])
    return d,m,cmd,launch,owner,clock


def test_three_concurrent_cycles_and_authenticated_drain(tmp_path):
    d,m,cmd,_,_,clock=controller(tmp_path);barrier=threading.Barrier(4);release=threading.Event()
    def work(loop):
        with d.cycle(loop) as allowed:
            assert allowed
            with m.job(cmd) as ch:
                ch.phase='OBSERVED';ch.process=SimpleNamespace(pid=9,poll=lambda:0)
                barrier.wait(timeout=5);assert release.wait(5)
    with ThreadPoolExecutor(max_workers=3) as pool:
        fs=[pool.submit(work,n) for n in sorted(LOOPS)]
        barrier.wait(timeout=5);assert len(d.status()['active_loops'])==3
        proof=d.request_drain()
        with pytest.raises(ValueError):
            with d.cycle('v2-maintenance'):pass
        release.set();result=d.drain(proof,timeout=5)
        for f in fs:f.result()
    assert result['phase']=='QUIESCED_OBSERVATION' and result['completed']==3
    assert not result['lifecycle_authorized']
    with pytest.raises(ValueError):d.drain(proof)


def test_logical_clocks_preserve_periods_and_normal_restart_defaults(tmp_path):
    d,m,cmd,_,_,clock=controller(tmp_path)
    for loop in LOOPS:
        with d.cycle(loop) as yes:
            assert yes
            with m.job(cmd) as ch:ch.phase='OBSERVED';ch.process=SimpleNamespace(pid=9,poll=lambda:0)
        with d.cycle(loop) as yes:assert not yes
    assert d.next_due==PERIODS
    clock[0]=10
    with d.cycle('v2-maintenance') as yes:assert yes
    with d.cycle('slow-maintenance') as yes:assert not yes
    new=MaintenanceDrain(m,idle=lambda:{})
    assert new.status()['phase']=='DISABLED'
    with pytest.raises(ValueError):
        with new.cycle('v2-maintenance'):pass


@pytest.mark.parametrize('fault',['duplicate','generation','timeout','idle','clock','foreign','lost-ack'])
def test_uncertain_supervisor_state_holds(tmp_path,fault):
    d,m,cmd,launch,owner,clock=controller(tmp_path)
    if fault=='duplicate':
        with pytest.raises(ValueError):
            with d.cycle('slow-maintenance'):
                with d.cycle('slow-maintenance'):pass
    elif fault=='generation':
        launch.retire('maintain');raw=launch.prepare('maintain',owner)
        launch.accept('maintain',answer_launch(raw,owner,now=lambda:1))
        with pytest.raises(ValueError):
            with d.cycle('v2-maintenance'):pass
    elif fault=='foreign':
        with pytest.raises(ValueError):
            with d.cycle('atlas'):pass
    elif fault=='clock':
        with d.cycle('v2-maintenance'):pass
        clock[0]=-1
        with pytest.raises(ValueError):
            with d.cycle('v2-maintenance'):pass
    elif fault=='lost-ack':
        p=d.request_drain();p['mac']='0'*64
        with pytest.raises(ValueError):d.drain(p)
    elif fault=='idle':
        d.idle=lambda:{'active_children':1,'unresolved_jobs':0,'admission_closed':True}
        p=d.request_drain()
        with pytest.raises(ValueError):d.drain(p)
    else:
        # An admitted job may outlive the deadline; it is never cancelled or killed.
        entered=threading.Event();release=threading.Event()
        def task():
            try:
                with d.cycle('slow-maintenance'):entered.set();release.wait(5)
            except ValueError:pass
        t=threading.Thread(target=task);t.start();assert entered.wait(5)
        p=d.request_drain()
        try:
            with pytest.raises(ValueError):d.drain(p,timeout=.01)
            assert t.is_alive()
        finally:release.set();t.join(5)
    assert d.status()['phase']=='HOLD'


@pytest.mark.parametrize('marker,rollback,closed,expected',[
    (None,False,False,'AMBIGUOUS'),(None,False,True,'AMBIGUOUS'),
    (None,True,False,'AMBIGUOUS'),(None,True,True,'ROLLED_BACK'),
    ('valid',False,False,'COMMITTED'),('valid',False,True,'COMMITTED'),
    ('valid',True,True,'AMBIGUOUS'),('wrong',False,True,'AMBIGUOUS')])
def test_transaction_outcome_never_automatically_replays(marker,rollback,closed,expected):
    row=None if marker is None else {'operation_id':'op','operation_sha256':'a'*64 if marker=='valid' else 'b'*64}
    r=classify_transaction(operation_id='op',operation_sha256='a'*64,marker=row,rollback_confirmed=rollback,writer_closed=closed)
    assert r['status']==expected and r['automatic_replay'] is False


@pytest.mark.skipif(os.name!='nt',reason='Native Windows concurrent command and kernel evidence')
def test_real_concurrent_loops_with_test_clock_and_graceful_drain(tmp_path):
    import subprocess,sys,time
    import asyncpg,redis
    from test_genesis_recurring_maintenance import pinned,ROOT,source
    from scripts.genesis_private_child_entry import native
    Job=pytest.importorskip('scripts.genesis_native_descendants').OwnedDescendantJob
    pinned();db='gb07_'+__import__('uuid').uuid4().hex;base='postgresql://postgres@127.0.0.1:16606/'
    # Exact Redis pin is inspected independently; no production fallback or writes.
    cid=os.environ.get('GENESIS_OBSERVATION_REDIS_CONTAINER')
    if not cid:pytest.skip('Explicit isolated Redis fixture required')
    row=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
    assert row['Id']=='d2dd3eebbdfe4ab9eb5b28796e4904db1ca44f9ea6b8ecc38f186c897a03c633'
    assert row['Config']['Labels']['genesis.audit']=='background-auth-provenance-v1'
    assert row['HostConfig']['PortBindings']['6379/tcp']==[{'HostIp':'127.0.0.1','HostPort':'16603'}]
    assert not any(m['Type'] in ('bind','volume') for m in row['Mounts'])
    client=redis.Redis(host='127.0.0.1',port=16603,socket_timeout=3);assert client.ping();client.close()
    async def setup():
        c=await asyncpg.connect(base+'gb06');await c.execute('CREATE DATABASE '+db);await c.close()
        c=await asyncpg.connect(base+db);m=ROOT/'services/post-migration-collector/migrations'
        for n in ['001_post_migration_schema.sql','002_success_learning.sql','004_intelligence_shadow_scores.sql','005_intelligence_paper_decisions.sql','007_intelligence_execution_v2_registry.sql','008_intelligence_execution_v2_evidence.sql']:
            await c.execute((m/n).read_text())
        from scripts.freeze_intelligence_execution_v2 import policy,policy_hash,VERSION
        await c.execute("INSERT INTO intelligence_execution_v2_registry VALUES($1,$2,$3::jsonb,'2026-01-01Z')",VERSION,policy_hash(policy()),json.dumps(policy()))
        track=await c.fetchval("INSERT INTO migration_tracks(mint,migration_at) VALUES('GB07_SYNTHETIC',clock_timestamp()-interval '90seconds') RETURNING track_id")
        await c.execute("INSERT INTO market_snapshots(mint,price_usd,liquidity_usd,market_cap_usd,volume_m5_usd) VALUES('GB07_SYNTHETIC',1,2000,600000,100000)")
        await c.execute("INSERT INTO intelligence_shadow_scores(track_id,mint,shadow_version,score_version,calibration_version,calibration_sha256,horizon_sec,migration_at,cutoff_at,scored_at,feature_payload,score_payload,authority) SELECT track_id,mint,'fixture','genesis-evidence-score-v1','fixture',$1,60,migration_at,migration_at+interval '60seconds',clock_timestamp(),'{}','{\"status\":\"KNOWN\",\"score\":85}','evidence_only' FROM migration_tracks",'a'*64)
        await c.close()
    asyncio.run(setup())
    py=sys._base_executable
    commands={'slow-maintenance':(py,'-m','post_migration.cli','learn-success'),
              'research-maintenance':(py,str(ROOT/'scripts/run_intelligence_paper_decisions.py'),'--boundary','2026-01-01T00:00:00+00:00','--limit','500'),
              'v2-maintenance':(py,str(ROOT/'scripts/run_intelligence_execution_v2.py'))}
    sources={n:source('post_migration.cli') if n=='slow-maintenance' else Path(c[1]) for n,c in commands.items()}
    owner=native(os.getpid());launch=LaunchObservations(native);raw=launch.prepare('maintain',owner);launch.accept('maintain',answer_launch(raw,owner))
    jobs={};proofs=[];outputs=[];registry_lock=threading.Lock()
    def retirement(p,w):
        proof=jobs[p.pid].verified_exit()
        with registry_lock:proofs.append(proof)
        return {'root_pid':p.pid,'root_exit_code':0,'active_descendants':0,'identity_verified':True,'job_id':w['job_id'],'source_sha256':w['sha256']}
    m=MaintenanceObservation(launches=launch,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],manifest={n:[(c,sources[n])] for n,c in commands.items()},retirement=retirement)
    logical=[0.0]
    d=MaintenanceDrain(m,isolated=True,clock=lambda:logical[0],idle=lambda:{'active_children':sum(j.snapshot()['active_processes'] for j in jobs.values()),'unresolved_jobs':len(m.owners),'admission_closed':True})
    paths=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.venv/Lib/site-packages')]+[str(p) for p in (ROOT/'services').glob('*/src')]+[str(p) for p in (ROOT/'packages').glob('*/src')]
    env={**os.environ,'PYTHONPATH':os.pathsep.join(paths),'STINKY_DATABASE_URL':base.replace('postgresql:','postgresql+asyncpg:')+db,'STINKY_REDIS_URL':'redis://127.0.0.1:16603/0','STINKY_SOLANA_RPC_URL':'http://127.0.0.1:1'}
    def ticks(p):
        from ctypes import wintypes
        import ctypes
        k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
        k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];k.CloseHandle.argtypes=[wintypes.HANDLE]
        h=k.OpenProcess(0x1000,False,p.pid);assert h
        try:
            a=[wintypes.FILETIME() for _ in range(4)];assert k.GetProcessTimes(h,*[ctypes.byref(x) for x in a]);return (a[0].dwHighDateTime<<32)|a[0].dwLowDateTime
        finally:k.CloseHandle(h)
    def worker(loop,barrier):
        with d.cycle(loop) as admitted:
            assert admitted
            with m.job(commands[loop]) as ch:
                cmd=ch.command_for(commands[loop]);p=subprocess.Popen(cmd,cwd=tmp_path,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    root=native(p.pid);root['creation_ticks']=ticks(p)
                    def verify(pid):r=native(pid);r['creation_ticks']=ticks(p);return r
                    job=Job(p,root,verify)
                    with registry_lock:jobs[p.pid]=job
                    assert ch.deliver(p,cmd,owner,before_continue=lambda:barrier.wait(timeout=10) is not None)
                    out,err=p.communicate(timeout=30);assert p.returncode==0,'Isolated concurrent job failed; retained evidence'
                    with registry_lock:outputs.append({'loop':loop,'exit':p.returncode,'output':out[-3000:]})
                finally:
                    if p.stdin and not p.stdin.closed:p.stdin.close()
                    if p.poll() is None:(tmp_path/('HOLD-'+str(p.pid)+'.json')).write_text(json.dumps({'pid':p.pid}))
    async def waves():
        admin=await asyncpg.connect(base+db);wait_counts=[]
        try:
            for wave in range(2):
                logical[0]=wave*21600.0;tx=admin.transaction();await tx.start();await admin.execute('LOCK TABLE migration_tracks IN ACCESS EXCLUSIVE MODE')
                barrier=threading.Barrier(3)
                with ThreadPoolExecutor(max_workers=3) as pool:
                    fs=[pool.submit(worker,n,barrier) for n in sorted(commands)]
                    try:
                        deadline=time.monotonic()+30;maximum=0
                        while time.monotonic()<deadline:
                            await admin.execute('SELECT pg_stat_clear_snapshot()')
                            count=await admin.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=$1 AND wait_event_type='Lock'",db)
                            maximum=max(maximum,count)
                            if count>=3:break
                            if any(f.done() and f.exception() for f in fs):break
                            await asyncio.sleep(.05)
                        wait_counts.append(maximum)
                    finally:await tx.rollback()  # Always cooperatively release fixture-only lock.
                    for f in fs:f.result(timeout=45)
                assert maximum>=3,'Actual SQL overlap not established'
            proof=d.request_drain()
            with pytest.raises(ValueError,match='fenced'):
                with m.loop('v2-maintenance'):pytest.fail('Native direct-manager bypass')
            status=d.drain(proof,timeout=5)
            assert status['phase']=='QUIESCED_OBSERVATION' and status['completed']==6
            counts={t:await admin.fetchval('SELECT count(*) FROM '+t) for t in ['token_outcomes','intelligence_paper_decisions','intelligence_execution_v2_plans']}
            assert counts['token_outcomes']==1 and counts['intelligence_paper_decisions']==1
            return {'sql_wait_overlap':wait_counts,'counts':counts,'status':status}
        finally:await admin.close()
    try:
        result=asyncio.run(waves())
        (tmp_path/'concurrent-evidence.json').write_text(json.dumps({**result,'outputs':outputs,'kernel_retirement':proofs,'scope':'ISOLATED_TEST_SUPERVISOR_NOT_DESKTOP_BOOTSTRAP'},indent=2,default=str))
    finally:
        for j in jobs.values():j.close()


def test_cooperative_sql_interruption_and_reconciliation(tmp_path):
    import asyncpg,uuid
    from test_genesis_recurring_maintenance import pinned
    pinned();db='gb07_'+uuid.uuid4().hex;base='postgresql://postgres@127.0.0.1:16606/'
    class BeforeCommit(Exception):pass
    class AfterCommit(Exception):pass
    async def run():
        c=await asyncpg.connect(base+'gb06');await c.execute('CREATE DATABASE '+db);await c.close()
        w=await asyncpg.connect(base+db);r=await asyncpg.connect(base+db)
        await w.execute('CREATE TABLE effects(operation_id text PRIMARY KEY,operation_sha256 text NOT NULL)')
        evidence=[]
        try:
            try:
                async with w.transaction():
                    await w.execute("INSERT INTO effects VALUES('rollback',$1)",'a'*64)
                    marker=await r.fetchrow("SELECT * FROM effects WHERE operation_id='rollback'")
                    evidence.append(classify_transaction(operation_id='rollback',operation_sha256='a'*64,marker=marker,rollback_confirmed=False,writer_closed=False))
                    raise BeforeCommit()
            except BeforeCommit:pass
            await w.close();assert await r.fetchval('SELECT count(*) FROM effects')==0
            evidence.append(classify_transaction(operation_id='rollback',operation_sha256='a'*64,marker=None,rollback_confirmed=True,writer_closed=True))
            w=await asyncpg.connect(base+db)
            try:
                async with w.transaction():await w.execute("INSERT INTO effects VALUES('committed',$1)",'b'*64)
                raise AfterCommit()  # Lost job reply, without killing any process/backend.
            except AfterCommit:pass
            await w.close();marker=dict(await r.fetchrow("SELECT * FROM effects WHERE operation_id='committed'"))
            evidence.append(classify_transaction(operation_id='committed',operation_sha256='b'*64,marker=marker,rollback_confirmed=False,writer_closed=True))
            assert [e['status'] for e in evidence]==['AMBIGUOUS','ROLLED_BACK','COMMITTED']
            assert all(e['automatic_replay'] is False for e in evidence)
            assert await r.fetchval('SELECT count(*) FROM effects')==1
            (tmp_path/'sql-recovery-evidence.json').write_text(json.dumps(evidence,indent=2))
        finally:
            if not w.is_closed():await w.close()
            await r.close()
    asyncio.run(run())


def test_activity_watcher_refreshes_transaction_cached_statistics():
    import asyncpg
    from test_genesis_recurring_maintenance import pinned
    pinned()
    async def run():
        c=await asyncpg.connect('postgresql://postgres@127.0.0.1:16606/gb06');tx=c.transaction();await tx.start()
        try:
            q="SELECT count(*) FROM pg_stat_activity WHERE application_name='GB07_STAT_TEST'"
            assert await c.fetchval(q)==0
            other=await asyncpg.connect('postgresql://postgres@127.0.0.1:16606/gb06',server_settings={'application_name':'GB07_STAT_TEST'})
            try:
                assert await c.fetchval(q)==0
                await c.execute('SELECT pg_stat_clear_snapshot()')
                assert await c.fetchval(q)==1
            finally:await other.close()
        finally:await tx.rollback();await c.close()
    asyncio.run(run())


def test_completed_generation_cannot_be_reopened_by_new_controller(tmp_path):
    d,m,cmd,launch,owner,clock=controller(tmp_path)
    with pytest.raises(ValueError):MaintenanceDrain(m,isolated=True,idle=lambda:{})
    proof=d.request_drain();d.drain(proof)
    with pytest.raises(ValueError):MaintenanceDrain(m,isolated=True,idle=lambda:{})
    launch.retire('maintain');raw=launch.prepare('maintain',owner)
    launch.accept('maintain',answer_launch(raw,owner,now=lambda:1))
    fresh=MaintenanceDrain(m,isolated=True,idle=lambda:{})
    assert fresh.status()['phase']=='RUNNING'
    with pytest.raises(ValueError):d.request_drain()
    assert d.status()['phase']=='HOLD'


@pytest.mark.parametrize('field,value',[('operation_id',''),('operation_id','a'*129),('operation_sha256','z'*64),('writer_closed',1),('rollback_confirmed',None)])
def test_malformed_recovery_evidence_is_rejected(field,value):
    args={'operation_id':'op','operation_sha256':'a'*64,'marker':None,'rollback_confirmed':False,'writer_closed':True}
    args[field]=value
    with pytest.raises(ValueError):classify_transaction(**args)
