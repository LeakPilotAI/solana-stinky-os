import threading
import time
import pytest
from stinky_core.transport.redis_accounting import AccountingError
from test_redis_writer_broker import broker,register,request


@pytest.mark.parametrize('failure',[None,'timeout','unknown_connection','pid_reuse','lost_fence','uncertain'])
def test_cooperative_drain_only_certifies_complete_owned_settlement(broker,failure):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer)
    token=request(b,'begin_command',writer,'XACK',[b'key',b'group',b'1-0'],11,1)
    entered=threading.Event();waiting=threading.Event();original_wait=b.admission_changed.wait
    def wait(seconds):waiting.set();return original_wait(seconds)
    b.admission_changed.wait=wait
    def inspect():entered.set();return [11,90] if failure=='unknown_connection' else [11]
    results=[]
    def drain():
        try:results.append(b.drain_registered(inspect,timeout=.25))
        except Exception as exc:results.append(type(exc))
    thread=threading.Thread(target=drain);thread.start()
    try:
        assert entered.wait(2)
        if failure!='unknown_connection':assert waiting.wait(2)
        with b.lock:
            assert b.fenced and credentials.fenced
            if failure=='pid_reuse':owner['creation_ticks']+=1
            if failure=='lost_fence':b.fenced=False
            if failure=='uncertain':ledger.uncertain.add(token)
        if failure is None:request(b,'complete_reply',token,1,'original')
        thread.join(2);assert not thread.is_alive()
        if failure:
            assert results==[AccountingError] and b.held and credentials.revocations
            assert ledger.commands[token]['state']=='ISSUED' and token in ledger.pending_commands
        else:
            assert results[0]['status']=='FENCED_DRAINED' and results[0]['acknowledged']==1
            assert b.fenced and not b.held and not ledger.pending_commands
    finally:thread.join(2)


@pytest.mark.parametrize('timeout',[0,-1,True,float('nan'),float('inf'),61,None])
def test_invalid_drain_deadline_never_changes_authority(broker,timeout):
    b,*_=broker
    with pytest.raises(AccountingError):b.drain_registered(lambda:[],timeout=timeout)
    assert not b.fenced and not b.held


def test_writers_cannot_invoke_controller_drain_rpc(broker):
    b,*_=broker
    with pytest.raises(AccountingError):request(b,'drain_registered',[])
    assert b.held


def test_slow_verification_cannot_report_drain_success_after_deadline(broker):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer)
    def inspect():time.sleep(.03);return [11]
    with pytest.raises(AccountingError,match='deadline'):b.drain_registered(inspect,timeout=.01)
    assert b.held and b.fenced and credentials.revocations
