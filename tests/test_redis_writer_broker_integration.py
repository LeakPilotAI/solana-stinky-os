"""Real Windows multi-process/Redis fixture; never targets production.

The protected fixture manifest is created only by the explicit isolated certifier.
Without that fixture, this integration test reports a skip, not certification.
"""
import asyncio
from contextlib import nullcontext
import hashlib
import json
import multiprocessing
import os
import subprocess
import threading
import uuid
from pathlib import Path

import pytest
import redis
import start_genesis as launcher
from redis.asyncio import Redis
from stinky_core.transport.redis_accounting import Runtime,ClientFactory,AccountingError
from scripts.redis_writer_broker import WriterBroker,PipeServer,PipeProxy,ProductionCredentials,PinnedRedisScope,RetentionBoundary
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements,writer_id
from scripts.guarded_redis_migration import NativePause
from scripts.genesis_process_diagnostics import native_identity
from scripts.redis_stream_integrity import semantic_census


def actor(channel):
    incoming=channel.recv();owner,address,key,port,epoch,role,server_identity=incoming[:7]
    adapter=NativePause()
    def verify():
        ticks,image=native_identity(adapter,os.getpid())
        assert ticks==owner['creation_ticks']
        return dict(owner)
    proxy=PipeProxy(address,key,[writer_id(owner,role)],server_identity=server_identity)
    runtime=Runtime(proxy,verify,endpoint='isolated67',server_epoch=epoch,roles=[role],credentials=proxy)
    if len(incoming)>=8:runtime.generation=incoming[7]
    group_name=incoming[8] if len(incoming)>=9 else 'group'
    participant=None;phase_journal=None
    if len(incoming)>=10 and incoming[9] is not None:
        from stinky_core.transport.cooperative_shutdown import CooperativeParticipant
        phase_journal=DurableJournal(Path(incoming[9])/f'{os.getpid()}-cooperative.jsonl')
        def persist_phase(row):phase_journal.persist(row);return phase_journal.previous
        admission={'accepting':True}
        def stop_jobs():admission['accepting']=False;return True
        participant=CooperativeParticipant(runtime,persist=persist_phase,stop_admission=stop_jobs)
    service_mode=len(incoming)>=11 and incoming[10] is True and participant is not None
    if service_mode:
        import stinky_core.transport.redis_accounting as accounting
        from stinky_core.transport import service_admission
        from scripts.genesis_supervisor_admission import SupervisorAdmission
        from scripts import run_genesis_service as service_runner
        supervisor_journal=DurableJournal(Path(incoming[9])/f'{os.getpid()}-supervisor.jsonl')
        def persist_supervisor(row):supervisor_journal.persist(row);return supervisor_journal.previous
        supervisor=SupervisorAdmission(owner,generation=runtime.generation,verify_native=verify,persist=persist_supervisor)
        service_runner.install_cooperative_supervisor(supervisor)
        factory=accounting.FACTORY
    else:factory=ClientFactory()
    factory.configure(runtime)
    if service_mode:service_admission.install(participant,factory=factory)
    closure_mode=service_mode and len(incoming)>=13 and incoming[12] is True
    # Real CollectorService.start uses socket_timeout=10 for its5000ms read.
    # redis-py's default5s socket timeout races a5s blocking server command.
    client=factory.from_url(f'redis://127.0.0.1:{port}/0',role=role,
        **({'socket_timeout':10} if closure_mode else {}))
    worker_task=None;delivery_journal=None
    if closure_mode:
        from stinky_core.transport.shutdown_delivery import ShutdownAuthority
        control_identity=hashlib.sha256(json.dumps(server_identity).encode()).hexdigest()
        control=ShutdownAuthority(incoming[11],control_identity)
        def verify_controller():
            assert native_identity(adapter,server_identity[0])[0]==server_identity[1]
            return control_identity
        delivery_journal=DurableJournal(Path(incoming[9])/f'{os.getpid()}-delivery.jsonl')
        def persist_delivery(row):delivery_journal.persist(row);return delivery_journal.previous
        service_admission.install_delivery(control,verify_controller=verify_controller,persist=persist_delivery)
        service_runner.install_shutdown_delivery(control,verify_controller=verify_controller,persist=persist_delivery)
    async def run():
        nonlocal worker_task
        try:
            while True:
                cmd=channel.recv()
                payload=None
                if isinstance(cmd,tuple):cmd,payload=cmd
                if cmd=='finish':break
                if cmd=='crash':os._exit(71)
                try:
                    control_commands=('cooperative','raw-after-fence','supervisor-stop','closure-metadata','auth-service','auth-supervisor','start-worker')
                    with (service_runner.supervisor_job([cmd]) if service_mode and cmd not in control_commands else nullcontext()):
                        async with (participant.job() if participant is not None and cmd not in control_commands+('service-push','service-lost') else nullcontext()):
                            if cmd=='closure-metadata':
                                value={'service_target':service_admission.DELIVERY.target(),
                                       'supervisor_target':service_runner.COOPERATIVE_DELIVERY.target()}
                            elif cmd=='auth-service':
                                value=await service_admission.deliver_shutdown(payload)
                                if worker_task is not None:await worker_task
                            elif cmd=='auth-supervisor':value=await service_runner.deliver_shutdown(payload)
                            elif cmd=='start-worker':
                                from stinky_core.transport.worker_closure import WorkerClosure
                                from post_migration.service import CollectorService
                                from post_migration.config import settings as collector_settings
                                from types import SimpleNamespace
                                WorkerClosure(participant,['collector-intake'])
                                collector_settings.event_stream='proof';collector_settings.collector_consumer_group=group_name+'-collector'
                                service=object.__new__(CollectorService);service._redis=client;service._running=False
                                entered=asyncio.Event()
                                async def startup():
                                    await client.xgroup_create('proof',collector_settings.collector_consumer_group,'$')
                                    service._running=True
                                async def backfill(**kwargs):return 0
                                service.start=startup;service._bounded_backfill=backfill
                                original_read=service._read_group
                                async def read(consumer):
                                    entered.set()
                                    try:return await original_read(consumer)
                                    except Exception as exc:
                                        cause=exc.__context__
                                        print('Isolated collector failure type:',type(cause).__module__,type(cause).__name__,
                                            'socket_timeout:',client.connection_pool.connection_kwargs.get('socket_timeout'),flush=True)
                                        raise
                                service._read_group=read
                                worker_task=asyncio.create_task(service.run_forever())
                                await entered.wait()
                                value={'worker':'collector-intake','entered':True}
                            elif cmd=='cooperative':
                                if participant is None:raise RuntimeError('No cooperative fixture grant')
                                value=await participant.quiesce({'request_id':'e'*32,'manifest_sha256':participant.manifest()},timeout=5)
                                assert not admission['accepting']
                            elif cmd=='supervisor-stop':
                                if not service_mode:raise RuntimeError('No supervisor fixture installation')
                                value=supervisor.quiesce({'request_id':'f'*32,'manifest_sha256':supervisor.manifest()},timeout=5)
                            elif cmd in ('service-push','service-lost'):
                                from stinky_api import track
                                track.MANUAL_QUEUE='queue';track.settings.redis_url=f'redis://127.0.0.1:{port}/0'
                                body=track.TrackRequest(mint='a'*28+'pump',note='fixture-lost' if cmd=='service-lost' else 'fixture-service')
                                original=Redis.execute_command
                                async def lose_reply(self,*args,**kwargs):
                                    reply=await original(self,*args,**kwargs)
                                    if str(args[0]).upper()=='LPUSH':raise redis.ConnectionError('Isolated lost reply')
                                    return reply
                                try:
                                    if cmd=='service-lost':Redis.execute_command=lose_reply
                                    value=await track.enqueue_manual_track(body)
                                finally:Redis.execute_command=original
                            elif cmd=='raw-after-fence':value=await Redis.execute_command(client,'XADD','proof','*','data','forbidden-after-boundary')
                            elif cmd=='bind':value=await client.ping()
                            elif cmd=='append':value=await client.xadd('proof',{'data':b'\x00\xff'})
                            elif cmd=='push':value=await client.lpush('queue','duplicate')
                            elif cmd=='group':
                                await client.xgroup_create('proof',group_name,'0')
                                await client.xreadgroup(group_name,'alpha',{'proof':'>'},count=1)
                                value=await client.xautoclaim('proof',group_name,'beta',0,'0-0',count=1)
                            elif cmd=='lost':
                                proxy.begin_command(client.writer,'LPUSH',[b'queue',b'unknown-accepted'],client.connection_id,runtime.generation)
                                value=await Redis.execute_command(client,'LPUSH','queue','unknown-accepted')
                            elif cmd=='trim':value=await client.xadd('proof',{'data':'discard'},maxlen=1)
                            elif cmd=='trim-safe':value=await client.xadd('proof',{'data':'retained'},maxlen=1,approximate=False)
                            elif cmd=='pop':value=await client.brpop('queue',timeout=1)
                            elif cmd=='disconnect':
                                await client.connection.disconnect()
                                value=await client.xadd('proof',{'data':'unreplayed'})
                            elif cmd=='bad-auth':
                                proxy.authkey=b'x'*32
                                value=await client.xadd('proof',{'data':'unauthenticated'})
                            elif cmd=='bad-server':
                                proxy.server_identity=(server_identity[0],server_identity[1]+1)
                                value=await client.xadd('proof',{'data':'spoofed-server'})
                            else:raise AssertionError('Unknown isolated command')
                    channel.send({'ok':True,'value':value})
                except Exception as exc:
                    if cmd in ('auth-service','auth-supervisor'):
                        print('Isolated shutdown refusal:',type(exc).__name__,
                              str(exc) if isinstance(exc,AccountingError) else 'HOLD',flush=True)
                    channel.send({'ok':False})
        finally:
            try:await client.aclose()
            except Exception:pass
            if phase_journal is not None:phase_journal.close()
            if service_mode:supervisor_journal.close()
            if delivery_journal is not None:delivery_journal.close()
            channel.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('GENESIS_BROKER_TEST_FIXTURE'),reason='Explicit protected isolated Redis fixture required')
def test_real_native_multiprocess_broker_and_fail_closed_boundaries():
    config=json.loads(Path(os.environ['GENESIS_BROKER_TEST_FIXTURE']).read_text())
    pin=PinnedRedisScope(**config['pins'])
    def scope():return json.loads(subprocess.check_output(['docker','inspect',config['pins']['container_id']],text=True))
    pin(scope())  # Never accept production or a fixture with different storage.
    assert (config['pins']['certification'],config['pins']['port']) in [('checkpoint67',16570),('checkpoint68',16574),('checkpoint69',16578),('checkpoint71',16582),('checkpoint73',16587),('checkpoint74',16589)]
    port=config['pins']['port']
    group_name=config.get('group_name','group')
    observer=redis.Redis(host='127.0.0.1',port=port,username='observer',password=config['observer_password'],socket_timeout=3)
    root=Path(config['artifact_root'])
    assert observer.llen('queue')<=5000
    lost_reply_baseline=observer.lrange('queue',0,4999).count(b'unknown-accepted')
    adapter=NativePause()
    results={}
    scenarios=('normal','lost','crash','trim','pop','foreign','disconnect','bad-auth','bad-server')
    if config.get('service_integration',False):scenarios+=('service-lost',)
    for scenario in scenarios:
        context=multiprocessing.get_context('spawn');pairs=[];processes=[]
        address='\\\\.\\pipe\\genesis-c67-'+uuid.uuid4().hex;key=os.urandom(32)
        roles=['redis-streams','api-manual-queue','entity-consumer']
        for role in roles:
            parent,child=context.Pipe();p=context.Process(target=actor,args=(child,));p.start()
            child.close();pairs.append(parent);processes.append(p)
        manifest={};images={}
        native_rows={r[0]:r for r in launcher.list_win_processes()}
        for p in processes:
            ticks,image=native_identity(adapter,p.pid)
            # Independently observed native image/time; fixture identities are not
            # represented as Genesis production service ownership.
            images[p.pid]=image
            manifest[p.pid]={'pid':p.pid,'creation_ticks':ticks,'service':'fixture','command_sha256':hashlib.sha256(native_rows[p.pid][3].encode()).hexdigest(),'repository_sha256':hashlib.sha256(str(Path.cwd()).encode()).hexdigest()}
        def verify(pid):
            ticks,image=native_identity(adapter,pid);owner=manifest[pid]
            assert ticks==owner['creation_ticks'] and image==images[pid]
            return dict(owner)
        journal=DurableJournal(root/(scenario+'-broker.jsonl'))
        ledger=ProductionAcknowledgements(journal,[writer_id(manifest[p.pid],role) for p,role in zip(processes,roles)])
        broker=None
        admin=lambda:redis.Redis(host='127.0.0.1',port=port,username='broker',password=config['broker_password'],socket_timeout=3)
        authority=ProductionCredentials(admin,scope,lambda:dict(broker.current_owner),journal,scope_validator=pin,port=port,keys={'redis-streams':['proof'],'api-manual-queue':['queue'],'entity-consumer':['proof']},readers={'observer':config['observer_commands']})
        broker=WriterBroker(ledger,authority,manifest,verify,RetentionBoundary(observer.config_get('maxmemory-policy'),0),server_epoch=observer.info('server')['run_id'],endpoint='isolated67')
        server=PipeServer(address,key,broker,max_workers=8 if config.get('group_commit',False) else 1,
                          group_commit=config.get('group_commit',False))
        def serve():
            while True:
                try:server.serve_one()
                except (OSError,EOFError,ValueError):return
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        server_identity=(os.getpid(),native_identity(adapter,os.getpid())[0])
        control_keys=[os.urandom(32) for _ in processes]
        for p,ch,role,control_key in zip(processes,pairs,roles,control_keys):
            ch.send((manifest[p.pid],address,key,port,observer.info('server')['run_id'],role,server_identity,1,group_name,str(root) if config.get('cooperative',False) and scenario in ('normal','service-lost') else None,config.get('service_integration',False),control_key,config.get('closure_integration',False)))
        def ask(index,cmd):
            pairs[index].send(cmd);assert pairs[index].poll(20)
            return pairs[index].recv()
        try:
            assert all(ask(i,'bind')['ok'] for i in range(3))
            assert ask(0,'append')['ok'] and ask(0,'append')['ok']
            assert ask(1,'push')['ok'] and ask(1,'push')['ok']
            if scenario=='normal':assert ask(2,'group')['ok']
            active=lambda:[int(r['id']) for r in observer.client_list() if r.get('user') in authority.tickets]
            if scenario=='normal':
                if config.get('cooperative',False):
                    from scripts.genesis_cooperative_boundary import certify_participants
                    from scripts.redis_production_adapters import read_records
                    pairs[0].send('append');pairs[1].send('push')
                    assert pairs[0].poll(20) and pairs[1].poll(20)
                    assert pairs[0].recv()['ok'] and pairs[1].recv()['ok']
                    if config.get('service_integration',False):
                        assert ask(1,'service-push')['ok']
                        if config.get('closure_integration',False):
                            from stinky_core.transport.shutdown_delivery import ShutdownAuthority
                            controls=[ShutdownAuthority(key,hashlib.sha256(json.dumps(server_identity).encode()).hexdigest()) for key in control_keys]
                            assert ask(0,'start-worker')['ok']
                            metadata=[ask(i,'closure-metadata')['value'] for i in range(3)]
                            def authenticated(index,kind,target,request_id):
                                control=controls[index]
                                request=control.request(metadata[index][target],1,timeout=15)
                                request['body']['request_id']=request_id;request=control.seal(request['body'])
                                reply=ask(index,(kind,request));assert reply['ok']
                                ack=control.verify_reply(request,reply['value'])
                                assert not ask(index,(kind,request))['ok']
                                return {'ok':True,'value':ack}
                            supervisor_acks=[authenticated(i,'auth-supervisor','supervisor_target','f'*32) for i in range(3)]
                        else:supervisor_acks=[ask(i,'supervisor-stop') for i in range(3)]
                        assert all(row['ok'] and row['value']['phase']=='QUIESCED' for row in supervisor_acks)
                        for row in supervisor_acks:
                            ack=row['value'];records=read_records(root/f"{ack['owner']['pid']}-supervisor.jsonl",expected_head=ack['journal_head'])
                            assert [r['phase'] for r in records]==['FENCING','DRAINING','QUIESCED']
                    if config.get('closure_integration',False):
                        acks=[authenticated(i,'auth-service','service_target','e'*32) for i in range(3)]
                        assert acks[0]['value']['completed_workers']==['collector-intake']
                        reported=[]
                        for p,row in zip(processes,acks):
                            ownership=row['value'].pop('connection_ownership')
                            assert ownership['owner']==manifest[p.pid] and ownership['generation']==1
                            assert ownership['server_epoch']==broker.server_epoch
                            reported.extend(ownership['connection_ids'])
                            row['value'].pop('completed_workers')
                        assert set(reported)==set(active()) and len(reported)==len(set(reported))
                        results['authenticated_closure_executed']={'actual_collector_loop':True,
                            'delivery_processed':True,'replay_denied':True,'native_server_client_join':True}
                    else:acks=[ask(i,'cooperative') for i in range(3)]
                    assert all(row['ok'] and row['value']['phase']=='QUIESCED' for row in acks)
                    before=semantic_census(observer);boundary_journal=DurableJournal(root/'cooperative-boundary.jsonl')
                    try:
                        boundary=certify_participants(broker,request_id='e'*32,
                            acknowledgements=[row['value'] for row in acks],
                            journals={p.pid:root/f'{p.pid}-cooperative.jsonl' for p in processes},
                            inspect_connections=active,census=lambda:semantic_census(observer),audit=boundary_journal,timeout=5)
                        assert boundary['phase']=='WRITERS_FENCED_DRAINED'
                        if config.get('closure_integration',False):
                            # Quiet actual intake may poll again while the three
                            # authenticated controllers are joined. Every real
                            # delivery intent is still strictly accounted for.
                            assert 12 <= boundary['acknowledged'] <= 20
                        else:
                            assert boundary['acknowledged']==(10 if config.get('service_integration',False) else 9)
                    finally:boundary_journal.close()
                    assert not ask(0,'raw-after-fence')['ok']
                    assert not ask(0,'append')['ok']
                    assert before['keys']==semantic_census(observer)['keys']
                    assert broker.fenced and not broker.held
                    results['cooperative_executed']={'participant_count':3,'verified_phase_heads':True,
                        'post_boundary_raw_denied':True,'actual_api_path':config.get('service_integration',False),
                        'supervisor_path':config.get('service_integration',False)}
                else:
                    assert broker.quiesce(active())==7
                    broker.retention.verify(ledger,semantic_census(observer))
                    assert not ask(0,'append')['ok'] and broker.held
            elif scenario=='service-lost':
                before=observer.llen('queue')
                assert not ask(1,'service-lost')['ok']
                assert observer.llen('queue')==before+1
                assert json.loads(observer.lrange('queue',0,0)[0])['note']=='fixture-lost'
                assert not ask(1,'cooperative')['ok']
                with pytest.raises(RuntimeError):broker.quiesce(active())
                assert broker.held and any(row['state']=='ISSUED' for row in ledger.commands.values())
            elif scenario=='lost':
                assert ask(1,'lost')['ok']
                with pytest.raises(RuntimeError,match='Unresolved'):broker.quiesce(active())
                assert observer.lrange('queue',0,0)==[b'unknown-accepted']
            elif scenario=='crash':
                pairs[0].send('crash');processes[0].join(10);assert processes[0].exitcode==71
                with pytest.raises((RuntimeError,AssertionError)):broker.quiesce(active())
            elif scenario in ('trim','pop'):
                before=semantic_census(observer)
                assert not ask(0 if scenario=='trim' else 1,scenario)['ok']
                after=semantic_census(observer)
                assert before['keys']==after['keys'] and broker.held
            elif scenario=='disconnect':
                before=semantic_census(observer)
                assert not ask(0,'disconnect')['ok']
                with pytest.raises(RuntimeError):broker.quiesce(active())
                assert before['keys']==semantic_census(observer)['keys'] and broker.held
            elif scenario in ('bad-auth','bad-server'):
                before=semantic_census(observer)
                assert not ask(0,scenario)['ok']
                # The actor waits for the rejected server response. For a
                # native-server mismatch it may close before server processing.
                for _ in range(100):
                    if broker.held:break
                    import time
                    time.sleep(.01)
                assert broker.held and before['keys']==semantic_census(observer)['keys']
            else:
                proxy=PipeProxy(address,key,[],server_identity=server_identity)
                with pytest.raises(RuntimeError):proxy.settled()
                assert broker.held
            results[scenario]={'acknowledged':sum(r['state']=='ACKNOWLEDGED' for r in ledger.commands.values()),'unresolved':sum(r['state']=='ISSUED' for r in ledger.commands.values()),'held':broker.held,'head':journal.previous}
        finally:
            for ch,p in zip(pairs,processes):
                if p.is_alive():
                    try:ch.send('finish')
                    except (EOFError,OSError):pass
                p.join(10);assert not p.is_alive()  # Never kill an uncertain process.
                ch.close()
            server.close()
            # Revoke and persist the final record before closing its journal.
            # Previous principals remain retained, disabled and nonwriting.
            revocation=authority.revoke_all()
            assert revocation['verified'] is True
            if journal.failed:
                assert revocation=={'status':'HOLD','verified':True,'durable':False}
                assert broker.held and broker.fenced
            else:assert revocation['durable'] is True
            if scenario in results:results[scenario]['revocation']=revocation
            else:(root/(scenario+'-cleanup.json')).write_text(json.dumps({'revocation':revocation,'status':'FAILED_SCENARIO_NO_SUCCESS_CLAIM'}))
            journal.close()
        if config['pins']['certification'] in ('checkpoint68','checkpoint69','checkpoint71','checkpoint73','checkpoint74'):
            from scripts.redis_broker_recovery import recover_held_boundary
            recovered_journal=DurableJournal(root/(scenario+'-recovered.jsonl'))
            def revoke(principal):
                pin(scope());client=admin()
                try:client.execute_command('ACL','SETUSER',principal,'off','resetpass','-@all')
                finally:client.close()
            def verify_revoked(principal):
                pin(scope());client=admin()
                try:
                    policy=client.acl_getuser(principal)
                    return policy is not None and 'off' in policy['flags'] and not policy['passwords'] and policy['categories']==['-@all'] and not policy['commands'] and not policy['selectors']
                finally:client.close()
            try:
                recovered=recover_held_boundary(journal.path,expected_head=journal.previous,
                    next_journal=recovered_journal,revoke=revoke,verify_revoked=verify_revoked)
                assert recovered['held'] and recovered['fenced'] and recovered['next_generation']==2
                assert recovered['ledger'].commands==ledger.commands
                assert all(not row['active'] for row in recovered['ledger'].bindings.values())
                if scenario in ('lost','service-lost'):
                    with pytest.raises(RuntimeError,match='Unresolved'):recovered['ledger'].settled()
                else:assert recovered['ledger'].settled()==len(ledger.commands)
                results[scenario]['held_restart_recovery']=True
            finally:recovered_journal.close()
            if config['pins']['certification']=='checkpoint69' and scenario=='normal':
                results['reauthorization']=exercise_reauthorization(config,recovered,observer,scope,pin)
    assert observer.llen('queue')<=5000
    assert observer.lrange('queue',0,4999).count(b'unknown-accepted')==lost_reply_baseline+1
    results['stream_entries']=observer.xlen('proof');results['queue_entries']=observer.llen('queue')
    results['pending']=observer.xpending('proof',group_name)['pending']
    (root/'multiprocess-results.json').write_text(json.dumps(results,indent=2))
    observer.close()


def exercise_reauthorization(config,recovered,observer,scope,pin):
    from scripts.redis_broker_recovery import reauthorize_held_route,recover_held_boundary
    from scripts.redis_evidence_archive import EvidenceArchive,ArchivedRetention
    root=Path(config['artifact_root']);folder=root/'normal-custody';folder.mkdir()
    journal=DurableJournal(root/'reauthorized.jsonl')
    context=multiprocessing.get_context('spawn');processes=[];channels=[]
    roles=['redis-streams','api-manual-queue','entity-consumer']
    for role in roles:
        parent,child=context.Pipe();p=context.Process(target=actor,args=(child,));p.start()
        child.close();processes.append(p);channels.append(parent)
    adapter=NativePause();rows={r[0]:r for r in launcher.list_win_processes()};manifest={};images={}
    for p in processes:
        ticks,image=native_identity(adapter,p.pid);images[p.pid]=image
        manifest[p.pid]={'pid':p.pid,'creation_ticks':ticks,'service':'fixture',
            'command_sha256':hashlib.sha256(rows[p.pid][3].encode()).hexdigest(),
            'repository_sha256':hashlib.sha256(str(Path.cwd()).encode()).hexdigest()}
    def verify(pid):
        ticks,image=native_identity(adapter,pid)
        assert ticks==manifest[pid]['creation_ticks'] and image==images[pid]
        return dict(manifest[pid])
    port=config['pins']['port'];broker=None
    admin=lambda:redis.Redis(host='127.0.0.1',port=port,username='broker',password=config['broker_password'],socket_timeout=3)
    authority=ProductionCredentials(admin,scope,lambda:dict(broker.current_owner),journal,
        scope_validator=pin,port=port,keys={'redis-streams':['proof'],'api-manual-queue':['queue'],'entity-consumer':['proof']},readers={'observer':config['observer_commands']})
    broker=reauthorize_held_route(recovered,journal=journal,credentials=authority,manifest=manifest,
        verify_native=verify,retention=RetentionBoundary(observer.config_get('maxmemory-policy'),0),
        server_epoch=observer.info('server')['run_id'],endpoint='isolated67',
        authorize=lambda request:request['source_head']==recovered['source_head'] and request['generation']==2,
        grant_path=root/('reauthorize-'+recovered['source_head']+'.grant'),
        writer_roles={p.pid:[role] for p,role in zip(processes,roles)})
    def pinned_epoch():pin(scope());return observer.info('server')['run_id']
    custody=ArchivedRetention(EvidenceArchive(folder),observer,broker.ledger,scope=pinned_epoch,
                              configuration=observer.config_get('maxmemory-policy'),expiring_keys=0)
    broker.ledger.custody=custody;broker.retention=custody
    address='\\\\.\\pipe\\genesis-c69-'+uuid.uuid4().hex;key=os.urandom(32);server=PipeServer(address,key,broker)
    def serve():
        while True:
            try:server.serve_one()
            except (OSError,EOFError,ValueError):return
    threading.Thread(target=serve,daemon=True).start()
    server_identity=(os.getpid(),native_identity(adapter,os.getpid())[0])
    for p,ch,role in zip(processes,channels,roles):
        ch.send((manifest[p.pid],address,key,port,observer.info('server')['run_id'],role,server_identity,2))
    def ask(index,command):
        channels[index].send(command);assert channels[index].poll(20);return channels[index].recv()
    try:
        assert all(ask(i,'bind')['ok'] for i in range(3))
        assert ask(0,'append')['ok'] and ask(0,'append')['ok']
        assert ask(1,'push')['ok'] and ask(1,'push')['ok']
        assert ask(0,'trim-safe')['ok'] and observer.xlen('proof')==1
        assert len(custody.anchors)==1
        assert custody.verify(broker.ledger,semantic_census(observer))['acknowledged']==12
        active=[int(r['id']) for r in observer.client_list() if r.get('user') in authority.tickets]
        assert broker.quiesce(active)==12
        assert not ask(0,'append')['ok']  # Neither quiescence nor a grant auto-resumes.
        return {'generation':2,'acknowledged':12,'trimmed_stream_length':1,
                'verified_archives':1,'fresh_native_writers':3,'stale_principals_disabled':True}
    finally:
        for ch,p in zip(channels,processes):
            if p.is_alive():
                try:ch.send('finish')
                except (EOFError,OSError):pass
            p.join(10);assert not p.is_alive();ch.close()
        server.close();authority.revoke_all();head=journal.previous;journal.close()
        audit=DurableJournal(root/'reauthorized-held.jsonl')
        def revoke(principal):
            pin(scope());c=admin()
            try:c.execute_command('ACL','SETUSER',principal,'off','resetpass','-@all')
            finally:c.close()
        def revoked(principal):
            c=admin()
            try:
                p=c.acl_getuser(principal)
                return 'off' in p['flags'] and not p['passwords'] and not p['commands']
            finally:c.close()
        try:
            again=recover_held_boundary(journal.path,expected_head=head,next_journal=audit,
                revoke=revoke,verify_revoked=revoked,parent_loader=lambda h:recovered,
                verify_archive=lambda a:custody.store.read(a)[1]['schema']=='redis-recovery-semantic-v1')
            assert again['next_generation']==3 and again['ledger'].settled()==12 and len(again['archive_anchors'])==1
        finally:audit.close()
