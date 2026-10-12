from types import SimpleNamespace
import pytest
from scripts.redis_production_adapters import ProductionAcknowledgements
from stinky_core.transport.redis_accounting import AccountingError,DispatchBusy

OWNER={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}


def harness():
    rows=[]
    journal=SimpleNamespace(persist=lambda row:rows.append(row))
    ledger=ProductionAcknowledgements(journal,['writer'])
    ledger.register_connection('writer',OWNER,1,'c'*40,1)
    checks=[]
    def conflict(row,name):checks.append(row['token']);return row['command']=='XADD' and name=='XADD'
    ledger.custody=SimpleNamespace(single_flight_backpressure=True,conflicts=conflict,before=lambda *a:None)
    return ledger,rows,checks


def test_only_pending_receipts_participate_in_admission():
    ledger,rows,checks=harness()
    for n in range(100):
        token=ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'value'],1,1)
        ledger.complete_command(token,f'{n+1}-0',b'canonical-reply','fixture')
    assert len(ledger.commands)==100 and ledger.settled()==100 and checks==[]
    token=ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'pending'],1,1)
    with pytest.raises(DispatchBusy):ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'blocked'],1,1)
    assert checks==[token] and len(ledger.commands)==101


def test_blocking_group_delivery_does_not_block_producer_but_remains_unsettled():
    ledger,rows,checks=harness()
    token=ledger.begin_command('writer','XREADGROUP',[b'GROUP',b'g',b'c',b'BLOCK',b'5000',b'STREAMS',b'key',b'>'],1,1)
    assert ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'value'],1,1)==2
    assert token in ledger.pending_commands
    with pytest.raises(RuntimeError):ledger.settled()


def test_failed_durable_reply_keeps_conflict_and_uncertainty():
    ledger,rows,checks=harness()
    token=ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'value'],1,1)
    def fail(row):raise OSError('isolated disk failure')
    ledger.journal.persist=fail
    with pytest.raises(OSError):ledger.complete_command(token,'1-0',b'reply','fixture')
    assert ledger.commands[token]['state']=='ISSUED' and token in ledger.pending_commands
    with pytest.raises(DispatchBusy):ledger.begin_command('writer','XADD',[b'key',b'*',b'data',b'blocked'],1,1)
    with pytest.raises(OSError):ledger.mark_uncertain(token,'fixture')
    assert token in ledger.uncertain and token in ledger.pending_commands
    with pytest.raises(AccountingError):ledger.complete_command(token,'1-0',b'reply','fixture')


def test_known_no_effect_reply_removes_pending_only_after_durability():
    ledger,rows,checks=harness()
    token=ledger.begin_command('writer','XGROUP CREATE',[b'key',b'g',b'0'],1,1)
    ledger.reject_group_exists(token,'fixture')
    assert not ledger.pending_commands and ledger.settled()==1
    assert rows[-1]['outcome']=='REJECTED_NO_EFFECT'


@pytest.mark.parametrize('method',['begin','begin_metadata','acknowledged','acknowledged_metadata'])
def test_legacy_fixture_methods_cannot_bypass_registered_admission(method):
    ledger,rows,checks=harness();before=len(rows)
    with pytest.raises(AccountingError,match='registered physical'):
        getattr(ledger,method)('writer',b'key',[b'f',b'v'])
    assert not ledger.commands and not ledger.pending_commands and len(rows)==before
