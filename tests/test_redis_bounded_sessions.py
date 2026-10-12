import json,os,struct,threading,uuid
from types import SimpleNamespace
import pytest
from scripts.redis_writer_broker import (PipeServer,PipeProxy,WriterBroker,RetentionBoundary,
    native_creation,session_frame,read_session_frame,session_limit)
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements
from stinky_core.transport.redis_accounting import AccountingError


@pytest.mark.parametrize('limit',[0,257,True,None,1.0])
def test_session_bounds_fail_closed(limit):
    with pytest.raises(AccountingError):session_limit(limit)


@pytest.mark.parametrize('change',['payload','direction','ordinal','session','truncated','deadline'])
def test_authenticated_frames_reject_replay_and_corruption(change):
    key=b'k'*32;session=b's'*64+struct.pack('>I',0);raw=session_frame(key,b'response',session,b'{"value":1}')
    expected=session;direction=b'response'
    if change=='payload':raw=raw[:-1]+b'!'
    if change=='direction':direction=b'request'
    if change=='ordinal':expected=b's'*64+struct.pack('>I',1)
    if change=='session':expected=b't'*64+struct.pack('>I',0)
    if change=='truncated':raw=raw[:31]
    connection=SimpleNamespace(poll=lambda timeout:change!='deadline',recv_bytes=lambda bound:raw)
    with pytest.raises(AccountingError):read_session_frame(connection,key,direction,expected)


@pytest.mark.skipif(os.name!='nt',reason='Native Windows named pipe identity required')
@pytest.mark.parametrize('limit',[1,2,8])
def test_native_session_reuses_only_verified_ordered_requests(tmp_path,limit):
    pid=os.getpid();birth=native_creation(pid)
    owner={'pid':pid,'creation_ticks':birth,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}
    checks=[];revocations=[]
    def verify(p):
        assert p==pid and native_creation(p)==birth;checks.append(p);return owner
    journal=DurableJournal(tmp_path/'ledger.jsonl');ledger=ProductionAcknowledgements(journal,['fixture'])
    broker=WriterBroker(ledger,SimpleNamespace(revoke_all=lambda:revocations.append(True)),{pid:owner},verify,
        RetentionBoundary({'maxmemory-policy':'noeviction'},0),server_epoch='c'*40,endpoint='fixture')
    address='\\\\.\\pipe\\genesis-c72-test-'+uuid.uuid4().hex
    server=PipeServer(address,b'k'*32,broker,max_workers=2,max_requests=limit)
    proxy=PipeProxy(address,b'k'*32,['fixture'],server_identity=(pid,birth),max_requests=limit)
    requests=5;connections=(requests+limit-1)//limit
    thread=threading.Thread(target=lambda:[server.serve_one() for _ in range(connections)],daemon=True);thread.start()
    try:
        for _ in range(requests):assert proxy.settled()==0
        proxy.close();thread.join(5);assert not thread.is_alive()
        server.close();assert not broker.held and not revocations
        assert broker.sequences[pid]==requests and len(checks)>=requests
    finally:
        proxy._disconnect();journal.close()


def test_lost_reply_poisoned_proxy_never_reconnects(monkeypatch):
    proxy=PipeProxy('unused',b'k'*32,[],server_identity=(1,10),max_requests=8)
    attempts=[]
    def fail():attempts.append(True);raise EOFError()
    monkeypatch.setattr(proxy,'_connect',fail)
    for _ in range(2):
        with pytest.raises(AccountingError):proxy.settled()
    assert attempts==[True] and proxy.failed


def test_explicit_closed_proxy_is_idempotent_and_cannot_regain_route(monkeypatch):
    proxy=PipeProxy('unused',b'k'*32,[],server_identity=(1,10),max_requests=8)
    attempts=[];monkeypatch.setattr(proxy,'_connect',lambda:attempts.append(True))
    proxy.close();proxy.close()
    with pytest.raises(AccountingError):proxy.settled()
    assert attempts==[] and proxy.closed


@pytest.mark.skipif(os.name!='nt',reason='Native Windows named pipe identity required')
@pytest.mark.parametrize('failure',['replay','lost_admission_reply'])
def test_native_session_failure_holds_without_replaying_intent(tmp_path,failure):
    pid=os.getpid();birth=native_creation(pid)
    owner={'pid':pid,'creation_ticks':birth,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}
    writer=f'{pid}-{birth}-redis-streams';journal=DurableJournal(tmp_path/'ledger.jsonl')
    ledger=ProductionAcknowledgements(journal,[writer]);revoked=[]
    credentials=SimpleNamespace(revoke_all=lambda:revoked.append(True),is_bound=lambda *a:True)
    broker=WriterBroker(ledger,credentials,{pid:owner},lambda p:owner,
        RetentionBoundary({'maxmemory-policy':'noeviction'},0),server_epoch='c'*40,endpoint='fixture')
    dispatch=broker.dispatch
    def inject(p,request):
        value=dispatch(p,request)
        if failure=='lost_admission_reply' and request['method']=='begin_command':raise EOFError('isolated lost reply')
        return value
    broker.dispatch=inject
    address='\\\\.\\pipe\\genesis-c72-failure-'+uuid.uuid4().hex
    server=PipeServer(address,b'k'*32,broker,max_workers=2,max_requests=8)
    thread=threading.Thread(target=server.serve_one,daemon=True);thread.start()
    proxy=PipeProxy(address,b'k'*32,[writer],server_identity=(pid,birth),max_requests=8)
    try:
        proxy.register_connection(writer,owner,11,'c'*40,1)
        if failure=='replay':proxy.sequence-=1
        with pytest.raises(AccountingError):proxy.begin_command(writer,'XADD',[b'key',b'*',b'data',b'value'],11,1)
        with pytest.raises(AccountingError):proxy.begin_command(writer,'XADD',[b'key',b'*',b'data',b'value'],11,1)
        thread.join(5);server.close()
        assert broker.held and broker.fenced and revoked and proxy.failed
        assert len(ledger.commands)==(1 if failure=='lost_admission_reply' else 0)
        if ledger.commands:
            assert ledger.commands[1]['state']=='ISSUED'
            with pytest.raises(RuntimeError):ledger.settled()
    finally:proxy._disconnect();journal.close()
