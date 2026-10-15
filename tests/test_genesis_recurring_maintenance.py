"""Explicit isolated real-job certification; never defaults to production DSNs."""
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

ROOT=Path(__file__).resolve().parents[1]


def pinned():
    raw=os.environ.get('GENESIS_GB06_PG_FIXTURE')
    if not raw:pytest.skip('Explicit isolated GB06 PostgreSQL pin required')
    v=json.loads(Path(raw).read_text())
    d=json.loads(subprocess.check_output(['docker','inspect',v['container_id']],text=True))[0]
    assert d['Id']==v['container_id'] and d['Name']=='/'+v['name'] and d['Image']==v['image']
    assert d['Config']['Labels']['genesis.certification']=='gb06' and d['State']['Running']
    assert not any(m['Type'] in ('bind','volume') for m in d['Mounts'])
    assert d['HostConfig']['PortBindings']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':'16606'}]
    assert v['port']==16606 and v['database']=='gb06'
    return v


def source(module):
    import importlib.util
    return Path(importlib.util.find_spec(module).origin)


@pytest.mark.skipif(os.name!='nt',reason='Native Windows job/IPC certification')
def test_real_six_maintenance_entries_and_repeat_with_kernel_retirement(tmp_path):
    import asyncpg
    from scripts.genesis_private_child_entry import native
    from scripts.genesis_launch_provenance import LaunchObservations,answer_launch
    from scripts.genesis_maintenance_observation import MaintenanceObservation
    # Existing preserved CP77 no-kill kernel witness; supplemental native fixture.
    Job=pytest.importorskip('scripts.genesis_native_descendants').OwnedDescendantJob
    pin=pinned();db='gb06_'+uuid.uuid4().hex
    base='postgresql://postgres@127.0.0.1:16606/'
    async def initialize():
        c=await asyncpg.connect(base+'gb06');await c.execute('CREATE DATABASE '+db);await c.close()
        c=await asyncpg.connect(base+db)
        migrations=ROOT/'services/post-migration-collector/migrations'
        for n in ['001_post_migration_schema.sql','002_success_learning.sql','004_intelligence_shadow_scores.sql','005_intelligence_paper_decisions.sql','007_intelligence_execution_v2_registry.sql','008_intelligence_execution_v2_evidence.sql']:
            await c.execute((migrations/n).read_text())
        from scripts.freeze_intelligence_execution_v2 import policy,policy_hash,VERSION
        await c.execute("INSERT INTO intelligence_execution_v2_registry VALUES($1,$2,$3::jsonb,'2026-01-01Z')",VERSION,policy_hash(policy()),json.dumps(policy()))
        track=await c.fetchval("INSERT INTO migration_tracks(mint,migration_at) VALUES('GB06_SYNTHETIC',clock_timestamp()-interval '90 seconds') RETURNING track_id")
        await c.execute("INSERT INTO market_snapshots(mint,captured_at,price_usd,liquidity_usd,volume_m5_usd,market_cap_usd) VALUES('GB06_SYNTHETIC',clock_timestamp()-interval '40 seconds',1,2000,100000,600000)")
        await c.execute("INSERT INTO migration_buyers(track_id,mint,wallet,rank,signature,bought_at,sol_spent) VALUES($1,'GB06_SYNTHETIC','GB06_WALLET',1,'GB06_BUY',clock_timestamp()-interval '80 seconds',1)",track)
        await c.execute("INSERT INTO wallet_trades(mint,wallet,side,signature,traded_at,token_amount,sol_amount,usd_amount,price_usd) VALUES('GB06_SYNTHETIC','GB06_WALLET','buy','GB06_TRADE',clock_timestamp(),1,1,1,1)")
        await c.close()
    asyncio.run(initialize())
    cal=tmp_path/'calibration.json'
    profile={'tertile_bounds':[1,2],'buckets':{b:{'n':10,'rates':{'RUNNER':.8,'FADE':.1}} for b in ['LOW','MID','HIGH']}}
    regimes={name:{'bounds':bounds,'adequate_for_directional_use':True,'feature_profiles':{f:profile for f in ['liquidity_usd','volume_m5_usd','early_buyer_count','meaningful_buyer_count']}} for name,bounds in [('low',[None,1000000]),('mid',[1000000,2000000]),('high',[2000000,None])]}
    cal.write_text(json.dumps({'profile_version':'GB06_SYNTHETIC_NOT_PRODUCTION','horizons':{'60':{'market_cap_regimes':regimes}}}))
    py=sys._base_executable;boundary='2026-01-01T00:00:00+00:00'
    commands=[('slow-maintenance',(py,'-m','post_migration.cli','learn-success'),source('post_migration.cli')),
      ('slow-maintenance',(py,'-m','post_migration.cli','recompute-performance'),source('post_migration.cli')),
      ('research-maintenance',(py,str(ROOT/'scripts/run_intelligence_shadow_scorer.py'),'--boundary',boundary,'--limit','500','--calibration',str(cal)),ROOT/'scripts/run_intelligence_shadow_scorer.py'),
      ('research-maintenance',(py,str(ROOT/'scripts/run_intelligence_paper_decisions.py'),'--boundary',boundary,'--limit','500'),ROOT/'scripts/run_intelligence_paper_decisions.py'),
      ('research-maintenance',(py,str(ROOT/'scripts/run_intelligence_paper_execution_plans.py'),'--boundary',boundary,'--limit','500'),ROOT/'scripts/run_intelligence_paper_execution_plans.py'),
      ('v2-maintenance',(py,str(ROOT/'scripts/run_intelligence_execution_v2.py')),ROOT/'scripts/run_intelligence_execution_v2.py')]
    owner=native(os.getpid());launch=LaunchObservations(native)
    frame=launch.prepare('maintain',owner);launch.accept('maintain',answer_launch(frame,owner))
    jobs={};proofs=[]
    def retired(proc,work):
        proof=jobs[proc.pid].verified_exit();proofs.append(proof)
        return {'root_pid':proc.pid,'root_exit_code':proof['root_exit_code'],'active_descendants':proof['active_processes'],'identity_verified':True,'job_id':work['job_id'],'source_sha256':work['sha256']}
    manager=MaintenanceObservation(launches=launch,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest={loop:[(cmd,src) for l,cmd,src in commands if l==loop] for loop in ['slow-maintenance','research-maintenance','v2-maintenance']},retirement=retired)
    paths=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.venv/Lib/site-packages')]+[str(p) for p in (ROOT/'services').glob('*/src')]+[str(p) for p in (ROOT/'packages').glob('*/src')]
    env={**os.environ,'PYTHONPATH':os.pathsep.join(paths),'STINKY_DATABASE_URL':base.replace('postgresql:','postgresql+asyncpg:')+db,
         'STINKY_REDIS_URL':'redis://127.0.0.1:1/0','STINKY_SOLANA_RPC_URL':'http://127.0.0.1:1'}
    def tick(proc):
        from ctypes import wintypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
        k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];k.CloseHandle.argtypes=[wintypes.HANDLE]
        h=k.OpenProcess(0x1000,False,proc.pid);assert h
        try:
            ts=[wintypes.FILETIME() for _ in range(4)];assert k.GetProcessTimes(h,*[ctypes.byref(t) for t in ts])
            return (ts[0].dwHighDateTime<<32)|ts[0].dwLowDateTime
        finally:k.CloseHandle(h)
    outputs=[]
    try:
        for loop,cmd,src in commands+[commands[0],commands[1]]:
            with manager.loop(loop),manager.job(cmd) as channel:
                wrapped=channel.command_for(cmd)
                proc=subprocess.Popen(wrapped,cwd=tmp_path,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    initial=native(proc.pid);initial['creation_ticks']=tick(proc)
                    def verify(pid):
                        row=native(pid);row['creation_ticks']=tick(proc);return row
                    jobs[proc.pid]=Job(proc,initial,verify)
                    assert channel.deliver(proc,wrapped,owner)
                    out,err=proc.communicate(timeout=30)
                    assert proc.returncode==0, 'Isolated real maintenance entry failed; inspect retained fixture'
                    outputs.append({'loop':loop,'entry':src.name,'exit':proc.returncode,'output':out[-4000:]})
                finally:
                    if proc.stdin and not proc.stdin.closed:proc.stdin.close()
                    if proc.poll() is None:(tmp_path/'HOLD.json').write_text(json.dumps({'pid':proc.pid}))
            assert manager.phase=='READY' and not manager.owners
        async def check():
            c=await asyncpg.connect(base+db)
            counts={t:await c.fetchval('SELECT count(*) FROM '+t) for t in ['token_outcomes','wallet_performance','intelligence_shadow_scores','intelligence_paper_decisions','intelligence_paper_execution_plans','intelligence_execution_v2_plans']}
            assert all(n==1 for n in counts.values()),counts
            result=await c.fetchval('SELECT count(*) FROM intelligence_execution_v2_results');assert result==0
            await c.close();return counts
        counts=asyncio.run(check())
        (tmp_path/'certification.json').write_text(json.dumps({'counts':counts,'outputs':outputs,'kernel_retirement':proofs,'scope':'SYNTHETIC_DB_REAL_ENTRIES_NOT_PRODUCTION'},default=str,indent=2))
    finally:
        for job in jobs.values():job.close()  # No kill-on-close, failed fixtures retained.


@pytest.mark.parametrize('fault',['valid','active-descendant','wrong-pid','bad-boolean','missing-proof','verifier-error','nonzero-exit','missing-child-ack','stale-generation','replayed-proof'])
def test_explicit_retirement_evidence_and_uncertain_retry_hold(tmp_path,fault):
    from types import SimpleNamespace
    from scripts.genesis_launch_provenance import LaunchObservations,answer_launch
    from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS
    owner={'pid':1,'parent_pid':0,'created':'2026-10-15T00:00:00+00:00','executable':'fixture','command_sha256':'a'*64}
    launches=LaunchObservations(lambda pid:owner,now=lambda:1)
    raw=launches.prepare('maintain',owner);launches.accept('maintain',answer_launch(raw,owner,now=lambda:1))
    script=tmp_path/'job.py';script.write_text('pass')
    cmd=(str(Path(sys.executable).resolve()),str(script))
    def verify(proc,work):
        if fault=='verifier-error':raise RuntimeError('Native evidence disconnected')
        if fault=='missing-proof':return None
        return {'root_pid':8 if fault=='wrong-pid' else 9,'root_exit_code':0,
                'active_descendants':1 if fault=='active-descendant' else 0,
                'identity_verified':1 if fault=='bad-boolean' else True,
                'job_id':'replayed' if fault=='replayed-proof' else work['job_id'],'source_sha256':work['sha256']}
    m=MaintenanceObservation(launches=launches,native=lambda pid:owner,ancestry=lambda c,p:True,
        manifest={loop:[(cmd,script)] for loop in LOOPS},retirement=verify)
    def cycle():
        with m.loop('slow-maintenance'),m.job(cmd) as channel:
            channel.phase='HOLD' if fault=='missing-child-ack' else 'OBSERVED'
            channel.process=SimpleNamespace(pid=9,poll=lambda:1 if fault=='nonzero-exit' else 0)
            if fault=='stale-generation':launches.retire('maintain')
    if fault=='valid':cycle();assert m.phase=='READY'
    else:
        with pytest.raises((ValueError,RuntimeError)):cycle()
        assert m.phase=='HOLD'
        with pytest.raises(ValueError):cycle()  # No implicit replay after uncertain completion.


def test_retirement_verifier_opt_in_preserves_existing_constructor(tmp_path):
    from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS
    script=tmp_path/'job.py';script.write_text('pass')
    with pytest.raises(ValueError):MaintenanceObservation(launches=None,native=lambda pid:{},ancestry=lambda c,p:True,
        manifest={loop:[((sys.executable,str(script)),script)] for loop in LOOPS},retirement=True)


@pytest.mark.skipif(os.name!='nt',reason='Native private real CLI failure path')
@pytest.mark.parametrize('fault',['cli-rejection','database-refused'])
def test_real_entry_failure_holds_without_automatic_retry(tmp_path,fault):
    pinned()
    from scripts.genesis_private_child_entry import native
    from scripts.genesis_launch_provenance import LaunchObservations,answer_launch
    from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS
    cmd=(sys._base_executable,'-m','post_migration.cli','--gb06-invalid') if fault=='cli-rejection' else (sys._base_executable,'-m','post_migration.cli','learn-success')
    src=source('post_migration.cli');owner=native(os.getpid());launch=LaunchObservations(native)
    raw=launch.prepare('maintain',owner);launch.accept('maintain',answer_launch(raw,owner))
    verified=[]
    m=MaintenanceObservation(launches=launch,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest={loop:[(cmd,src)] for loop in LOOPS},retirement=lambda p,w:verified.append(True))
    paths=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.venv/Lib/site-packages')]+[str(p) for p in (ROOT/'services').glob('*/src')]+[str(p) for p in (ROOT/'packages').glob('*/src')]
    env={**os.environ,'PYTHONPATH':os.pathsep.join(paths),'STINKY_DATABASE_URL':'postgresql+asyncpg://postgres@127.0.0.1:16606/gb06_deliberately_absent',
         'STINKY_REDIS_URL':'redis://127.0.0.1:1/0'}
    with pytest.raises(ValueError,match='unresolved'):
        with m.loop('slow-maintenance'),m.job(cmd) as channel:
            wrapped=channel.command_for(cmd)
            p=subprocess.Popen(wrapped,cwd=tmp_path,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                assert channel.deliver(p,wrapped,owner)
                out,err=p.communicate(timeout=30)
                assert p.returncode in (1,2)
            finally:
                if p.stdin and not p.stdin.closed:p.stdin.close()
                if p.poll() is None:(tmp_path/'HOLD.json').write_text(json.dumps({'pid':p.pid}))
    assert m.phase=='HOLD' and m.count==1 and not verified
    with pytest.raises(ValueError):
        with m.loop('slow-maintenance'):pytest.fail('Uncertain job implicitly retried')
