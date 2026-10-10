"""Real Windows multi-process/Redis fixture; never targets production.

The protected fixture manifest is created only by the explicit isolated certifier.
Without that fixture, this integration test reports a skip, not certification.
"""
import asyncio
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
from stinky_core.transport.redis_accounting import Runtime,ClientFactory
from scripts.redis_writer_broker import WriterBroker,PipeServer,PipeProxy,ProductionCredentials,PinnedRedisScope,RetentionBoundary
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements,writer_id
from scripts.guarded_redis_migration import NativePause
from scripts.genesis_process_diagnostics import native_identity
from scripts.redis_stream_integrity import semantic_census


def actor(channel):
    owner,address,key,port,epoch,role,server_identity=channel.recv()
    adapter=NativePause()
    def verify():
        ticks,image=native_identity(adapter,os.getpid())
        assert ticks==owner['creation_ticks']
        return dict(owner)
    proxy=PipeProxy(address,key,[writer_id(owner,role)],server_identity=server_identity)
    runtime=Runtime(proxy,verify,endpoint='isolated67',server_epoch=epoch,roles=[role],credentials=proxy)
    factory=ClientFactory();factory.configure(runtime)
    client=factory.from_url(f'redis://127.0.0.1:{port}/0',role=role)
    async def run():
        try:
            while True:
                cmd=channel.recv()
                if cmd=='finish':break
                if cmd=='crash':os._exit(71)
                try:
                    if cmd=='bind':value=await client.ping()
                    elif cmd=='append':value=await client.xadd('proof',{'data':b'\x00\xff'})
                    elif cmd=='push':value=await client.lpush('queue','duplicate')
                    elif cmd=='group':
                        await client.xgroup_create('proof','group','0')
                        await client.xreadgroup('group','alpha',{'proof':'>'},count=1)
                        value=await client.xautoclaim('proof','group','beta',0,'0-0',count=1)
                    elif cmd=='lost':
                        proxy.begin_command(client.writer,'LPUSH',[b'queue',b'unknown-accepted'],client.connection_id,runtime.generation)
                        value=await Redis.execute_command(client,'LPUSH','queue','unknown-accepted')
                    elif cmd=='trim':value=await client.xadd('proof',{'data':'discard'},maxlen=1)
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
                except Exception:
                    channel.send({'ok':False})
        finally:
            try:await client.aclose()
            except Exception:pass
            channel.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('GENESIS_BROKER_TEST_FIXTURE'),reason='Explicit protected isolated Redis fixture required')
def test_real_native_multiprocess_broker_and_fail_closed_boundaries():
    config=json.loads(Path(os.environ['GENESIS_BROKER_TEST_FIXTURE']).read_text())
    pin=PinnedRedisScope(**config['pins'])
    def scope():return json.loads(subprocess.check_output(['docker','inspect',config['pins']['container_id']],text=True))
    pin(scope())  # Never accept production or a fixture with different storage.
    assert config['pins']['certification']=='checkpoint67' and config['pins']['port']==16570
    observer=redis.Redis(host='127.0.0.1',port=16570,username='observer',password=config['observer_password'],socket_timeout=3)
    root=Path(config['artifact_root'])
    adapter=NativePause()
    results={}
    for scenario in ('normal','lost','crash','trim','pop','foreign','disconnect','bad-auth','bad-server'):
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
        admin=lambda:redis.Redis(host='127.0.0.1',port=16570,username='broker',password=config['broker_password'],socket_timeout=3)
        authority=ProductionCredentials(admin,scope,lambda:dict(broker.current_owner),journal,scope_validator=pin,port=16570,keys={'redis-streams':['proof'],'api-manual-queue':['queue'],'entity-consumer':['proof']},readers={'observer':config['observer_commands']})
        broker=WriterBroker(ledger,authority,manifest,verify,RetentionBoundary(observer.config_get('maxmemory-policy'),0),server_epoch=observer.info('server')['run_id'],endpoint='isolated67')
        server=PipeServer(address,key,broker)
        def serve():
            while True:
                try:server.serve_one()
                except (OSError,EOFError,ValueError):return
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        server_identity=(os.getpid(),native_identity(adapter,os.getpid())[0])
        for p,ch,role in zip(processes,pairs,roles):
            ch.send((manifest[p.pid],address,key,16570,observer.info('server')['run_id'],role,server_identity))
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
                assert broker.quiesce(active())==7
                broker.retention.verify(ledger,semantic_census(observer))
                assert not ask(0,'append')['ok'] and broker.held
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
            authority.revoke_all();journal.close()
    assert observer.lrange('queue',0,-1).count(b'unknown-accepted')==1
    results['stream_entries']=observer.xlen('proof');results['queue_entries']=observer.llen('queue')
    results['pending']=observer.xpending('proof','group')['pending']
    (root/'multiprocess-results.json').write_text(json.dumps(results,indent=2))
    observer.close()
