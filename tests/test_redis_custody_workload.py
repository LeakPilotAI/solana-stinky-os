"""Explicit isolated native workload; absent fixture is a skip, not certification."""
import asyncio,hashlib,json,multiprocessing,os,subprocess,threading,time,uuid
from pathlib import Path
import pytest,redis
import start_genesis as launcher
from scripts.guarded_redis_migration import NativePause
from scripts.genesis_process_diagnostics import native_identity
from scripts.redis_writer_broker import WriterBroker,PipeServer,PipeProxy,ProductionCredentials,PinnedRedisScope
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements,writer_id
from scripts.redis_evidence_archive import EvidenceArchive
from scripts.redis_append_custody import AppendStore,AppendCustody
from scripts.redis_stream_integrity import semantic_census
from scripts.redis_broker_recovery import recover_held_boundary
from stinky_core.transport.redis_accounting import Runtime,ClientFactory,DispatchBusy

def actor(channel):
    owner,address,key,port,epoch,role,server_identity=channel.recv()
    adapter=NativePause()
    def verify():
        ticks,image=native_identity(adapter,os.getpid());assert ticks==owner['creation_ticks']
        return dict(owner)
    proxy=PipeProxy(address,key,[writer_id(owner,role)],server_identity=server_identity)
    runtime=Runtime(proxy,verify,endpoint='isolated71',server_epoch=epoch,roles=[role],credentials=proxy)
    factory=ClientFactory();factory.configure(runtime)
    client=factory.from_url(f'redis://127.0.0.1:{port}/0',role=role)
    async def work():
        try:
            while True:
                cmd=channel.recv()
                if cmd=='finish':break
                if cmd=='crash':os._exit(71)
                try:
                    if cmd=='bind':value=await client.ping()
                    elif isinstance(cmd,dict) and cmd['task']=='group':
                        value=await client.xgroup_create('proof',cmd['group'],'0',mkstream=True)
                    elif cmd=='trim':value=await client.xadd('proof',{'data':b'exact trim'},maxlen=1,approximate=False)
                    elif cmd=='pop':value=await client.brpop('queue',timeout=1)
                    elif isinstance(cmd,dict):
                        start=cmd['start'];end=start+cmd['seconds'];latencies=[];count=0;failures=0
                        while time.perf_counter()<start:await asyncio.sleep(.001)
                        while time.perf_counter()<end+10:
                            if time.perf_counter()>=end:
                                if role in ('redis-streams','api-manual-queue'):break
                                groups=await client.xinfo_groups('proof')
                                lag=next(g['lag'] for g in groups if g['name']==cmd['group'].encode())
                                if lag==0:break
                            before=time.perf_counter()
                            if role=='redis-streams':
                                try:await client.xadd('proof',{'data':b'x'*cmd['payload_bytes']},maxlen=20000)
                                except DispatchBusy:
                                    # Known NOT dispatched/acknowledged. Preserve
                                    # and report explicit refusal; never pretend
                                    # this met the accepted-ingestion target.
                                    failures+=1;await asyncio.sleep(.01);continue
                                count+=1;latencies.append(time.perf_counter()-before)
                                if len(latencies)>12000:raise AssertionError('Bounded benchmark exceeded')
                                wait=start+count/cmd['rate']-time.perf_counter()
                                if wait>0:await asyncio.sleep(wait)
                            elif role=='api-manual-queue':
                                await client.lpush('queue',b'bounded manual request');count+=1
                                await asyncio.sleep(1)
                            else:
                                found=await client.xreadgroup(cmd['group'],'native-'+str(os.getpid()),{'proof':'>'},count=20 if role=='collector-consumer' else 500,block=5000)
                                for _,entries in found:
                                    for entry,_ in entries:
                                        await client.xack('proof',cmd['group'],entry);count+=1
                        value={'count':count,'latencies':latencies,'seconds':time.perf_counter()-start,'failures':failures}
                    else:raise AssertionError('Unknown benchmark action')
                    channel.send({'ok':True,'value':value})
                except Exception as exc:channel.send({'ok':False,'failure_type':type(exc).__name__})
        finally:
            try:await client.aclose()
            except Exception:pass
            channel.close()
    asyncio.run(work())

def percentile(rows,fraction):
    import math
    return sorted(rows)[max(0,math.ceil(len(rows)*fraction)-1)] if rows else None

@pytest.mark.skipif(not os.environ.get('GENESIS_CUSTODY_TEST_FIXTURE'),reason='Explicit protected isolated custody fixture required')
def test_real_concurrent_custody_and_recovery(monkeypatch):
    config=json.loads(Path(os.environ['GENESIS_CUSTODY_TEST_FIXTURE']).read_text())
    assert config['pins']['certification']=='checkpoint71' and config['pins']['port']==16582
    pin=PinnedRedisScope(**config['pins'])
    def scope():return json.loads(subprocess.check_output(['docker','inspect',config['pins']['container_id']],text=True))
    pin(scope());port=config['pins']['port'];root=Path(config['artifact_root'])
    observer=redis.Redis(host='127.0.0.1',port=port,username='observer',password=config['observer_password'],socket_timeout=10)
    epoch=observer.info('server')['run_id'];context=multiprocessing.get_context('spawn')
    roles=['redis-streams']*3+['collector-consumer','entity-consumer','api-manual-queue']
    processes=[];channels=[];manifest={};images={};adapter=NativePause()
    for role in roles:
        parent,child=context.Pipe();p=context.Process(target=actor,args=(child,));p.start();child.close()
        processes.append(p);channels.append(parent)
    native_rows={r[0]:r for r in launcher.list_win_processes()}
    for p in processes:
        ticks,image=native_identity(adapter,p.pid);images[p.pid]=image
        manifest[p.pid]={'pid':p.pid,'creation_ticks':ticks,'service':'fixture','command_sha256':hashlib.sha256(native_rows[p.pid][3].encode()).hexdigest(),'repository_sha256':hashlib.sha256(str(Path.cwd()).encode()).hexdigest()}
    def verify(pid):
        ticks,image=native_identity(adapter,pid);assert ticks==manifest[pid]['creation_ticks'] and image==images[pid]
        return dict(manifest[pid])
    journal=DurableJournal(root/'workload-ledger.jsonl')
    ledger=ProductionAcknowledgements(journal,[writer_id(manifest[p.pid],r) for p,r in zip(processes,roles)])
    address='\\\\.\\pipe\\genesis-c71-'+uuid.uuid4().hex;key=os.urandom(32);broker=None
    admin=lambda:redis.Redis(host='127.0.0.1',port=port,username='broker',password=config['broker_password'],socket_timeout=10)
    authority=ProductionCredentials(admin,scope,lambda:dict(broker.current_owner),journal,scope_validator=pin,port=port,
        keys={'redis-streams':['proof'],'collector-consumer':['proof'],'entity-consumer':['proof'],'api-manual-queue':['queue']},readers={'observer':config['observer_commands']})
    segment_dir=root/'append-segments';segment_dir.mkdir();base_dir=root/'base-archive';base_dir.mkdir()
    store=AppendStore(segment_dir);base=EvidenceArchive(base_dir)
    custody=AppendCustody(store,base,observer,ledger,scope=lambda:observer.info('server')['run_id'],
                         configuration=observer.config_get('maxmemory-policy'),expiring_keys=0)
    ledger.custody=custody
    broker=WriterBroker(ledger,authority,manifest,verify,custody,server_epoch=epoch,endpoint='isolated71')
    custody.initialize()
    timings={};timing_lock=threading.Lock()
    def timed(call,label):
        def wrapper(*args,**kwargs):
            start=time.perf_counter()
            try:return call(*args,**kwargs)
            finally:
                elapsed=time.perf_counter()-start
                with timing_lock:
                    row=timings.setdefault(label,{'calls':0,'seconds':0.0,'maximum_seconds':0.0})
                    row['calls']+=1;row['seconds']+=elapsed;row['maximum_seconds']=max(row['maximum_seconds'],elapsed)
        return wrapper
    monkeypatch.setattr(os,'fsync',timed(os.fsync,'fsync'))
    monkeypatch.setattr(journal,'persist',timed(journal.persist,'journal_persist'))
    monkeypatch.setattr(store,'prepare',timed(store.prepare,'custody_prepare'))
    monkeypatch.setattr(custody,'observe',timed(custody.observe,'entry_observation'))
    monkeypatch.setattr(broker,'owner',timed(broker.owner,'native_owner_check'))
    server=PipeServer(address,key,broker,max_workers=config.get('broker_workers',1))
    def serve():
        while True:
            try:server.serve_one()
            except (OSError,EOFError,ValueError):return
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    server_identity=(os.getpid(),native_identity(adapter,os.getpid())[0])
    for p,ch,role in zip(processes,channels,roles):ch.send((manifest[p.pid],address,key,port,epoch,role,server_identity))
    def ask(i,cmd):
        channels[i].send(cmd);assert channels[i].poll(30);result=channels[i].recv();assert result['ok'],result
        return result['value']
    results={};reference=config['criteria']['reference_appends_per_second']
    try:
        for i in range(6):assert ask(i,'bind')
        ask(3,{'task':'group','group':'collector'});ask(4,{'task':'group','group':'entities'})
        for phase,seconds,multiplier in [('reference',20,1),('sustained',20,2),('burst',5,4)]:
            target=reference*multiplier;start=time.perf_counter()+.5
            with timing_lock:timing_before=copy_timings(timings)
            memory_before=observer.info('memory')['used_memory']
            for i,ch in enumerate(channels):ch.send({'task':'work','start':start,'seconds':seconds,'rate':target/3,'group':'collector' if i==3 else 'entities','payload_bytes':config['criteria']['payload_bytes']})
            actor_rows=[]
            for ch in channels:
                assert ch.poll(seconds+25);result=ch.recv();assert result['ok'],result;actor_rows.append(result['value'])
            latencies=[v for row in actor_rows[:3] for v in row['latencies']]
            count=sum(row['count'] for row in actor_rows[:3]);throughput=count/seconds
            groups=observer.xinfo_groups('proof');backlog=sum(g['lag'] or 0 for g in groups)
            results[phase]={'target_appends_per_second':target,'appends':count,'appends_per_second':throughput,
                'median_ack_sec':percentile(latencies,.5),'p90_ack_sec':percentile(latencies,.9),'p99_ack_sec':percentile(latencies,.99),'max_ack_sec':max(latencies),
                'unresolved_commands':sum(r['state']!='ACKNOWLEDGED' for r in ledger.commands.values()),
                'consumer_lag':backlog,'used_memory_before':memory_before,'used_memory_after':observer.info('memory')['used_memory'],
                'pre_dispatch_backpressure':sum(row['failures'] for row in actor_rows),
                'custody_disk_bytes':store.total,'journal_bytes':journal.bytes,'custody_segments':store.count,
                'capacity_passed':throughput>=target*.95 and percentile(latencies,.99)<=1 and backlog==0 and not any(row['failures'] for row in actor_rows)}
            results[phase]['timings']={label:{'calls':row['calls']-timing_before.get(label,{}).get('calls',0),
                'seconds':row['seconds']-timing_before.get(label,{}).get('seconds',0),
                'maximum_seconds':row['maximum_seconds']} for label,row in timings.items()}
            assert ledger.settled()==len(ledger.commands) and not broker.held
        # All acknowledged payloads must remain independently verifiable after
        # exact retention removes almost the entire current stream.
        assert ask(0,'trim')
        assert observer.xlen('proof')==1
        assert custody.verify(ledger,semantic_census(observer))['observed_append_records']==len(store.records)
        store.seal(journal);head=journal.previous
        reader=AppendStore(segment_dir,writable=False)
        held_journal=DurableJournal(root/'workload-recovered-held.jsonl')
        def revoke(principal):
            pin(scope());client=admin()
            try:client.execute_command('ACL','SETUSER',principal,'off','resetpass','-@all')
            finally:client.close()
        def verify_revoked(principal):
            pin(scope());client=admin()
            try:
                policy=client.acl_getuser(principal)
                return 'off' in policy['flags'] and policy['passwords']==[] and policy['categories']==['-@all']
            finally:client.close()
        recovered=recover_held_boundary(journal.path,expected_head=head,next_journal=held_journal,
            revoke=revoke,verify_revoked=verify_revoked,
            verify_archive=lambda anchor:base.read(anchor) is not None,
            read_append=reader.read,verify_append_inventory=reader.verify_inventory)
        assert recovered['held'] and recovered['ledger'].settled()==len(ledger.commands)
        held_journal.close()
        results['integrity']={'acknowledged':len(ledger.commands),'custody_records':len(store.records),'strict_trim_verified':True,'held_recovery_verified':True,'head':head,'seals':store.seals}
        # Capacity is a reported acceptance gate, never silently waived by the
        # success of the distinct byte-integrity test.
        results['capacity_verdict']='GREEN' if all(results[p]['capacity_passed'] for p in ('reference','sustained','burst')) else 'BLOCKED'
        (root/'workload-results.json').write_text(json.dumps(results,indent=2))
        assert not ask_pop_safely(channels[5])
    finally:
        for ch,p in zip(channels,processes):
            if p.is_alive():
                try:ch.send('finish')
                except (EOFError,OSError):pass
            p.join(15);assert not p.is_alive();ch.close()
        server.close();authority.revoke_all();store.close();journal.close();observer.close()

def ask_pop_safely(channel):
    channel.send('pop');assert channel.poll(20);return channel.recv()['ok']

def copy_timings(rows):return {label:dict(value) for label,value in rows.items()}
