import os,subprocess,sys
import pytest
from scripts.redis_production_adapters import DurableJournal,read_records
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from test_redis_append_custody import fixture,apply,ARGS,WRITER


def test_observed_entry_and_receipt_share_one_flush_before_ack(fixture,monkeypatch):
    store,custody,ledger,journal,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1);apply(state,b'2-0',ARGS[5:])
    flush=os.fsync;calls=[]
    def verify(fd):
        assert ledger.commands[token]['state']=='ISSUED' and token not in custody.observed
        calls.append(fd);flush(fd)
    monkeypatch.setattr(os,'fsync',verify)
    ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    assert len(calls)==1 and ledger.settled()==1
    assert [r['stage'] for r in read_records(journal.path,expected_head=journal.previous)][-2:]==['CUSTODY_OBSERVED','COMMAND_REPLY']


def test_failed_combined_flush_never_settles_or_discards_custody(fixture,monkeypatch):
    store,custody,ledger,journal,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1);apply(state,b'2-0',ARGS[5:]);head=journal.previous
    def fail(fd):raise OSError('isolated fsync failure')
    monkeypatch.setattr(os,'fsync',fail)
    with pytest.raises(OSError):ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    assert journal.failed and journal.previous==head and custody.held
    assert ledger.commands[token]['state']=='ISSUED' and token in ledger.pending_commands
    assert token not in custody.observed and store.read(store.records[token])==ARGS
    with pytest.raises(AccountingError):read_records(journal.path,expected_head=head)
    with pytest.raises(AccountingError):journal.persist({'stage':'NO_RETRY'})


@pytest.mark.parametrize('records',[[],[{}]*9,None])
def test_batch_bound_is_enforced_without_disk_write(tmp_path,records):
    journal=DurableJournal(tmp_path/'ledger')
    try:
        with pytest.raises(AccountingError):journal.persist_many(records)
        assert journal.bytes==0 and journal.sequence==0 and journal.path.stat().st_size==0
    finally:journal.close()


def test_batch_capacity_failure_preserves_prior_head(tmp_path):
    journal=DurableJournal(tmp_path/'ledger',max_bytes=300)
    try:
        journal.persist({'stage':'first'});head=journal.previous
        with pytest.raises(AccountingError):journal.persist_many([{'stage':'large','data':'x'*300}])
        assert read_records(journal.path,expected_head=head)==[{'stage':'first'}]
    finally:journal.close()


def test_process_crash_after_batch_flush_preserves_order_and_complete_records(tmp_path):
    path=tmp_path/'crash-ledger';head=tmp_path/'independent-head'
    code="""
import os,sys
from pathlib import Path
from scripts.redis_production_adapters import DurableJournal
j=DurableJournal(sys.argv[1]);j.persist_many([{'stage':'observed'},{'stage':'receipt'}])
with Path(sys.argv[2]).open('xb') as f:
 f.write(j.previous.encode());f.flush();os.fsync(f.fileno())
os._exit(72)
"""
    result=subprocess.run([sys.executable,'-c',code,str(path),str(head)],timeout=10,capture_output=True)
    assert result.returncode==72
    assert read_records(path,expected_head=head.read_text())==[{'stage':'observed'},{'stage':'receipt'}]
    raw=path.read_bytes();path.write_bytes(raw.splitlines(keepends=True)[0])
    with pytest.raises(AccountingError):read_records(path,expected_head=head.read_text())
