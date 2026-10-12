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
from scripts.redis_append_custody import AppendStore,AppendCustody,FixedReadonlyEntryProbe
from scripts.redis_stream_integrity import semantic_census
from scripts.redis_broker_recovery import recover_held_boundary
from stinky_core.transport.redis_accounting import Runtime,ClientFactory,DispatchBusy
from redis.asyncio import Redis as AsyncRedis

def actor(channel):
    owner,address,key,port,epoch,role,server_identity,max_requests,stream_key=channel.recv()
    adapter=NativePause()
    def verify():
        ticks,image=native_identity(adapter,os.getpid());assert ticks==owner['creation_ticks']
        return dict(owner)
    proxy=PipeProxy(address,key,[writer_id(owner,role)],server_identity=server_identity,max_requests=max_requests)
    actor_timings={}
    def timed_sync(call,label):
        def wrapper(*args,**kwargs):
            start=time.perf_counter()
            try:return call(*args,**kwargs)
            finally:
                row=actor_timings.setdefault(label,{'calls':0,'seconds':0.0})
                row['calls']+=1;row['seconds']+=time.perf_counter()-start
        return wrapper
    proxy.call=timed_sync(proxy.call,'authenticated_rpc')
    runtime=Runtime(proxy,verify,endpoint='isolated71',server_epoch=epoch,roles=[role],credentials=proxy)
    runtime.check=timed_sync(runtime.check,'native_actor_check')
    factory=ClientFactory();factory.configure(runtime)
    client=factory.from_url(f'redis://127.0.0.1:{port}/0',role=role)
    if role=='collector-consumer':
        from post_migration.service import CollectorService
        from post_migration.config import settings as collector_settings
    if role=='entity-consumer':
        from entity_resolver.service import EntityService,ENTITY_RELEVANT_EVENT_TYPES
    def timed_async(call,label):
        async def wrapper(*args,**kwargs):
            start=time.perf_counter()
            try:return await call(*args,**kwargs)
            finally:
                row=actor_timings.setdefault(label,{'calls':0,'seconds':0.0})
                row['calls']+=1;row['seconds']+=time.perf_counter()-start
        return wrapper
    client._binding_observation=timed_async(client._binding_observation,'physical_binding_probe')
    physical_execute=AsyncRedis.execute_command
    async def profiled_execute(self,*args,**kwargs):
        return await timed_async(physical_execute,'physical_'+str(args[0]).upper())(self,*args,**kwargs)
    AsyncRedis.execute_command=profiled_execute
    async def work():
        try:
            while True:
                cmd=channel.recv()
                if cmd=='finish':break
                if cmd=='crash':os._exit(71)
                try:
                    if cmd=='bind':value=await client.ping()
                    elif isinstance(cmd,dict) and cmd['task']=='group':
                        value=await client.xgroup_create(stream_key,cmd['group'],'0',mkstream=True)
                    elif cmd=='trim':value=await client.xadd(stream_key,{'data':b'exact trim'},maxlen=1,approximate=False)
                    elif cmd=='pop':value=await client.brpop('queue',timeout=1)
                    elif isinstance(cmd,dict):
                        actor_timings.clear()
                        start=cmd['start'];end=start+cmd['seconds'];latencies=[];count=0;failures=0
                        cpu_before=time.process_time();read_batches=[];completed_in_window=0;event_types={}
                        while time.perf_counter()<start:await asyncio.sleep(.001)
                        while time.perf_counter()<end+10:
                            if time.perf_counter()>=end:
                                if role in ('redis-streams','api-manual-queue'):break
                                groups=await client.xinfo_groups(stream_key)
                                lag=next(g['lag'] for g in groups if g['name']==cmd['group'].encode())
                                if lag==0:break
                            before=time.perf_counter()
                            if role=='redis-streams':
                                payload=b'x'*cmd['payload_bytes']
                                if cmd.get('representative_mix'):
                                    # The bounded live sample had994/1000 wallet
                                    # performance,2 migration,2 quality,2 tracking.
                                    kind=('token.migrated' if cmd.get('migration_heavy') or count%500==0 else
                                          'quality.state_changed' if count%500==1 else
                                          'post_migration.tracking_started' if count%500==2 else 'wallet.performance_updated')
                                    body={'event_type':kind,'payload':{'padding':''}}
                                    empty=json.dumps(body,separators=(',',':')).encode()
                                    body['payload']['padding']='x'*(cmd['payload_bytes']-len(empty))
                                    payload=json.dumps(body,separators=(',',':')).encode()
                                    assert len(payload)==cmd['payload_bytes']
                                    event_types[kind]=event_types.get(kind,0)+1
                                try:await client.xadd(stream_key,{'data':payload},maxlen=20000)
                                except DispatchBusy:
                                    # Known NOT dispatched/acknowledged. Preserve
                                    # and report explicit refusal; never pretend
                                    # this met the accepted-ingestion target.
                                    failures+=1;await asyncio.sleep(.01);continue
                                count+=1;latencies.append(time.perf_counter()-before)
                                if time.perf_counter()<=end:completed_in_window+=1
                                if len(latencies)>12000:raise AssertionError('Bounded benchmark exceeded')
                                wait=start+count/cmd['rate']-time.perf_counter()
                                if wait>0:await asyncio.sleep(wait)
                            elif role=='api-manual-queue':
                                await client.lpush('queue',b'bounded manual request');count+=1
                                await asyncio.sleep(1)
                            else:
                                found=await client.xreadgroup(cmd['group'],'native-'+str(os.getpid()),{stream_key:'>'},count=20 if role=='collector-consumer' else 500,block=5000)
                                for _,entries in found:
                                    read_batches.append(len(entries))
                                    if cmd.get('representative_mix'):
                                        decoded=[(entry.decode(),{k.decode():v.decode() for k,v in fields.items()}) for entry,fields in entries]
                                        if role=='collector-consumer' and cmd.get('collector_batch'):
                                            collector_settings.event_stream=stream_key;collector_settings.collector_consumer_group=cmd['group']
                                            service=object.__new__(CollectorService);service._redis=client
                                            async def handle(identity,fields):
                                                # No synthetic database/migration
                                                # evidence. Only the Redis delivery
                                                # and receipt workload is measured.
                                                await client.xack(stream_key,cmd['group'],identity)
                                            service._handle_message=handle
                                            await service._handle_batch(decoded)
                                        elif role=='entity-consumer':
                                            ignored=[];relevant=[]
                                            for identity,fields in decoded:
                                                kind=EntityService._stream_event_type(fields)
                                                (ignored if kind is not None and kind not in ENTITY_RELEVANT_EVENT_TYPES else relevant).append(identity)
                                            if ignored:await client.xack(stream_key,cmd['group'],*ignored)
                                            for identity in relevant:await client.xack(stream_key,cmd['group'],identity)
                                        else:
                                            for identity,_ in decoded:await client.xack(stream_key,cmd['group'],identity)
                                        count+=len(entries)
                                    else:
                                        for entry,_ in entries:
                                            await client.xack(stream_key,cmd['group'],entry);count+=1
                        value={'count':count,'completed_in_window':completed_in_window,'latencies':latencies,'seconds':time.perf_counter()-start,'failures':failures,'timings':dict(actor_timings),'cpu_seconds':time.process_time()-cpu_before,'read_batches':read_batches,'event_types':event_types}
                    else:raise AssertionError('Unknown benchmark action')
                    channel.send({'ok':True,'value':value})
                except Exception as exc:channel.send({'ok':False,'failure_type':type(exc).__name__})
        finally:
            try:await client.aclose()
            except Exception:pass
            proxy.close()
            channel.close()
    asyncio.run(work())

def percentile(rows,fraction):
    import math
    return sorted(rows)[max(0,math.ceil(len(rows)*fraction)-1)] if rows else None

@pytest.mark.skipif(not os.environ.get('GENESIS_CUSTODY_TEST_FIXTURE'),reason='Explicit protected isolated custody fixture required')
def test_real_concurrent_custody_and_recovery(monkeypatch):
    config=json.loads(Path(os.environ['GENESIS_CUSTODY_TEST_FIXTURE']).read_text())
    assert (config['pins']['certification'],config['pins']['port']) in {('checkpoint71',16582),('checkpoint72',16586),('checkpoint73',16587)}
    pin=PinnedRedisScope(**config['pins'])
    def scope():return json.loads(subprocess.check_output(['docker','inspect',config['pins']['container_id']],text=True))
    pin(scope());port=config['pins']['port'];root=Path(config['artifact_root']);stream_key=config.get('stream_key','proof')
    assert isinstance(stream_key,str) and stream_key in ('proof','proof-trial-1','proof-trial-2','proof-trial-3','proof-trial-4','proof-trial-5')
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
        keys={'redis-streams':[stream_key],'collector-consumer':[stream_key],'entity-consumer':[stream_key],'api-manual-queue':['queue']},readers={'observer':config['observer_commands']})
    segment_dir=root/'append-segments';segment_dir.mkdir();base_dir=root/'base-archive';base_dir.mkdir()
    store=AppendStore(segment_dir);base=EvidenceArchive(base_dir)
    custody=AppendCustody(store,base,observer,ledger,scope=lambda:observer.info('server')['run_id'],
                         configuration=observer.config_get('maxmemory-policy'),expiring_keys=0,
                         entry_probe=FixedReadonlyEntryProbe(observer) if config.get('fixed_readonly_probe',False) else None)
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
    monkeypatch.setattr(journal,'persist_many',timed(journal.persist_many,'journal_batch_persist'))
    monkeypatch.setattr(store,'prepare',timed(store.prepare,'custody_prepare'))
    monkeypatch.setattr(custody,'observe',timed(custody.observe,'entry_observation'))
    monkeypatch.setattr(broker,'owner',timed(broker.owner,'native_owner_check'))
    monkeypatch.setattr(broker,'dispatch',timed(broker.dispatch,'serialized_broker_dispatch'))
    monkeypatch.setattr(broker.admission_changed,'wait',timed(broker.admission_changed.wait,'admission_condition_wait'))
    monkeypatch.setattr(broker.admission_changed,'notify_all',timed(broker.admission_changed.notify_all,'settlement_notification'))
    server=PipeServer(address,key,broker,max_workers=config.get('broker_workers',1),max_requests=config.get('session_requests',1))
    def serve():
        while True:
            try:server.serve_one()
            except (OSError,EOFError,ValueError):return
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    server_identity=(os.getpid(),native_identity(adapter,os.getpid())[0])
    for p,ch,role in zip(processes,channels,roles):ch.send((manifest[p.pid],address,key,port,epoch,role,server_identity,config.get('session_requests',1),stream_key))
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
            cpu_before=time.process_time()
            # Read-only, bounded sampling of the actual pipeline, not a synthetic
            # queue estimate. Sampling is diagnostic; never writer authorization.
            samples=[];sample_stop=threading.Event();sample_errors=[]
            def sample():
                try:
                    while not sample_stop.is_set() and len(samples)<750:
                        groups_now=observer.xinfo_groups(stream_key)
                        samples.append({'pending_intents':len(ledger.pending_commands),
                            'lag':sum(g['lag'] or 0 for g in groups_now),
                            'pending_deliveries':sum(g['pending'] for g in groups_now),
                            'redis_memory_bytes':observer.info('memory')['used_memory']})
                        sample_stop.wait(.1)
                except Exception as exc:sample_errors.append(type(exc).__name__)
            sampler=threading.Thread(target=sample,daemon=True);sampler.start()
            for i,ch in enumerate(channels):ch.send({'task':'work','start':start,'seconds':seconds,'rate':target*config.get('offered_margin',1)/3,'group':'collector' if i==3 else 'entities','payload_bytes':config['criteria']['payload_bytes'],
                'representative_mix':config.get('representative_mix',False),'collector_batch':config.get('collector_batch',False),'migration_heavy':config.get('migration_heavy',False)})
            actor_rows=[]
            for ch in channels:
                assert ch.poll(seconds+25);result=ch.recv();assert result['ok'],result;actor_rows.append(result['value'])
            sample_stop.set();sampler.join(15);assert not sampler.is_alive() and not sample_errors
            latencies=[v for row in actor_rows[:3] for v in row['latencies']]
            count=sum(row['count'] for row in actor_rows[:3])
            completed_in_window=sum(row['completed_in_window'] for row in actor_rows[:3]);throughput=completed_in_window/seconds
            groups=observer.xinfo_groups(stream_key);backlog=sum(g['lag'] or 0 for g in groups)
            results[phase]={'target_appends_per_second':target,'appends':count,'appends_per_second':throughput,
                'completed_in_window':completed_in_window,'late_settlements':count-completed_in_window,
                'event_types':[row['event_types'] for row in actor_rows[:3]],
                'offered_appends_per_second':target*config.get('offered_margin',1),
                'median_ack_sec':percentile(latencies,.5),'p90_ack_sec':percentile(latencies,.9),'p99_ack_sec':percentile(latencies,.99),'max_ack_sec':max(latencies),
                'p95_ack_sec':percentile(latencies,.95),'broker_cpu_seconds':time.process_time()-cpu_before,
                'actor_cpu_seconds':[row['cpu_seconds'] for row in actor_rows],
                'consumer_batches':[row['read_batches'] for row in actor_rows[3:5]],
                'queue_samples':len(samples),'peak_pending_intents':max(s['pending_intents'] for s in samples),
                'peak_consumer_lag':max(s['lag'] for s in samples),
                'peak_pending_deliveries':max(s['pending_deliveries'] for s in samples),
                'peak_redis_memory_bytes':max(s['redis_memory_bytes'] for s in samples),
                'unresolved_commands':sum(r['state']!='ACKNOWLEDGED' for r in ledger.commands.values()),
                'consumer_lag':backlog,'used_memory_before':memory_before,'used_memory_after':observer.info('memory')['used_memory'],
                'pre_dispatch_backpressure':sum(row['failures'] for row in actor_rows),
                'actor_timings':[row['timings'] for row in actor_rows],
                'custody_disk_bytes':store.total,'journal_bytes':journal.bytes,'custody_segments':store.count,
                'capacity_passed':throughput>=target*config.get('acceptance_fraction',.95) and percentile(latencies,.99)<=1 and backlog==0 and not any(row['failures'] for row in actor_rows)}
            results[phase]['timings']={label:{'calls':row['calls']-timing_before.get(label,{}).get('calls',0),
                'seconds':row['seconds']-timing_before.get(label,{}).get('seconds',0),
                'maximum_seconds':row['maximum_seconds']} for label,row in timings.items()}
            assert ledger.settled()==len(ledger.commands) and not broker.held
        # All acknowledged payloads must remain independently verifiable after
        # exact retention removes almost the entire current stream.
        assert ask(0,'trim')
        assert observer.xlen(stream_key)==1
        assert custody.verify(ledger,semantic_census(observer))['observed_append_records']==len(store.records)
        def inspect_writer_ids():
            client=admin()
            try:return [int(r['id']) for r in client.client_list() if r.get('user') in authority.tickets]
            finally:client.close()
        drained=broker.drain_registered(inspect_writer_ids,timeout=5)
        assert drained['acknowledged']==len(ledger.commands) and broker.fenced and not broker.held
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
        results['integrity']={'acknowledged':len(ledger.commands),'custody_records':len(store.records),'strict_trim_verified':True,'held_recovery_verified':True,'registered_drain':drained,'head':head,'seals':store.seals}
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
