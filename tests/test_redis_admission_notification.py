import threading
from types import SimpleNamespace
import pytest
from scripts.redis_writer_broker import WriterBroker
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements,writer_id
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from scripts.redis_append_custody import AppendCustody
from test_redis_writer_broker import broker,register,request


@pytest.mark.parametrize('filtered',[False,True])
def test_group_ack_only_wakes_waiters_when_the_custody_conflict_requires_it(broker,filtered):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer)
    ledger.custody=SimpleNamespace(before=lambda *a:None,
        **({'admission_notification_required':AppendCustody.admission_notification_required} if filtered else {}))
    notifications=[]
    b.admission_changed.notify_all=lambda:notifications.append(True)
    token=request(b,'begin_command',writer,'XACK',[b'key',b'group',b'1-0'],11,1)
    request(b,'complete_reply',token,1,'original')
    assert notifications==([] if filtered else [True])
    assert ledger.commands[token]['state']=='ACKNOWLEDGED' and ledger.settled()==1
    token=request(b,'begin_command',writer,'XADD',[b'key',b'*',b'f',b'v'],11,1)
    request(b,'complete_reply',token,b'2-0','original')
    assert len(notifications)==(1 if filtered else 2)
    assert ledger.settled()==2
    b.quiesce([11])
    assert len(notifications)==(2 if filtered else 3) and b.fenced


@pytest.mark.parametrize('failure',[None,'pid_reuse','credentials','fence','sequence','failed_receipt'])
def test_waiting_admission_rechecks_authority_and_only_follows_durable_settlement(tmp_path,failure):
    owners={pid:{'pid':pid,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64} for pid in (1,2)}
    current={p:dict(o) for p,o in owners.items()};bound=[True];revoked=[]
    journal=DurableJournal(tmp_path/'ledger.jsonl')
    writers={p:writer_id(o,'redis-streams') for p,o in owners.items()}
    ledger=ProductionAcknowledgements(journal,list(writers.values()))
    custody=SimpleNamespace(single_flight_backpressure=True,conflicts=lambda row,name:row['command']=='XADD' and name=='XADD',before=lambda *a:None)
    ledger.custody=custody
    credentials=SimpleNamespace(is_bound=lambda *a:bound[0],revoke_all=lambda:revoked.append(True))
    broker=WriterBroker(ledger,credentials,owners,lambda p:current[p],custody,server_epoch='c'*40,endpoint='fixture')
    def request(pid,method,*args):
        return broker.dispatch(pid,{'sequence':broker.sequences.get(pid,0)+1,'method':method,'args':list(args)})
    for pid in (1,2):request(pid,'register_connection',writers[pid],owners[pid],pid+10,'c'*40,1)
    token=request(1,'begin_command',writers[1],'XADD',[b'key',b'*',b'f',b'first'],11,1)
    waiting=threading.Event();wait=broker.admission_changed.wait
    def observe_wait(seconds):waiting.set();return wait(seconds)
    broker.admission_changed.wait=observe_wait;results=[]
    def contender():
        try:results.append(request(2,'begin_command',writers[2],'XADD',[b'key',b'*',b'f',b'second'],12,1))
        except Exception as exc:results.append(type(exc))
    thread=threading.Thread(target=contender);thread.start()
    try:
        assert waiting.wait(2)
        with broker.lock:
            assert len(ledger.commands)==1 and ledger.commands[token]['state']=='ISSUED'
            if failure=='pid_reuse':current[2]['creation_ticks']=11
            if failure=='credentials':bound[0]=False
            if failure=='fence':broker.fenced=True
            if failure=='sequence':broker.sequences[2]+=1
            if failure=='failed_receipt':
                def fail(row):raise OSError('isolated receipt failure')
                journal.persist=fail
        if failure=='failed_receipt':
            with pytest.raises(OSError):request(1,'complete_command',token,b'1-0',reply_bytes(b'1-0'),'fixture')
        else:request(1,'complete_command',token,b'1-0',reply_bytes(b'1-0'),'fixture')
        thread.join(2);assert not thread.is_alive()
        if failure:
            assert results==[AccountingError] and broker.held and revoked and len(ledger.commands)==1
        else:
            assert results==[2] and not broker.held
            assert ledger.commands[1]['state']=='ACKNOWLEDGED' and ledger.commands[2]['state']=='ISSUED'
    finally:thread.join(2);journal.close()
