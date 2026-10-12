import os,subprocess,sys
import pytest
from scripts.redis_production_adapters import DurableJournal,read_records
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from test_redis_append_custody import fixture,apply,ARGS,WRITER,EPOCH


def test_anchor_and_exact_intent_share_metadata_flush_before_admission(fixture,monkeypatch):
    store,custody,ledger,journal,state=fixture
    custody.initialize();flush=os.fsync;calls=[]
    def verify(fd):
        assert not ledger.commands and not ledger.pending_commands
        calls.append(fd);flush(fd)
    monkeypatch.setattr(os,'fsync',verify)
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    assert len(calls)==2  # Segment payload, then anchor+intent; never deferred.
    rows=read_records(journal.path,expected_head=journal.previous)
    assert [r['stage'] for r in rows[-2:]]==['APPEND_CUSTODY','COMMAND_INTENT']
    assert rows[-2]['anchor']['token']==rows[-1]['token']==token
    assert store.read(rows[-2]['anchor'])==ARGS
    assert ledger.commands[token]['state']=='ISSUED'


def test_failed_intent_flush_retains_segment_and_never_admits(fixture,monkeypatch):
    store,custody,ledger,journal,state=fixture
    custody.initialize();flush=os.fsync;calls=[];head=journal.previous
    def fail_second(fd):
        calls.append(fd)
        if len(calls)==2:raise OSError('isolated intent flush failure')
        flush(fd)
    monkeypatch.setattr(os,'fsync',fail_second)
    with pytest.raises(OSError):ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    assert journal.failed and store.held and custody.held
    assert not ledger.commands and not ledger.pending_commands and journal.previous==head
    assert store.total>0 and not store.records
    with pytest.raises(AccountingError):read_records(journal.path,expected_head=head)
    with pytest.raises(AccountingError):ledger.begin_command(WRITER,'XADD',ARGS,11,1)


def test_existing_preparation_cannot_silently_skip_atomic_intent(fixture):
    store,custody,ledger,journal,state=fixture
    custody.initialize();anchor=store.prepare(1,ARGS,epoch=EPOCH,journal=journal)
    with pytest.raises(AccountingError,match='Existing custody'):
        ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    assert not ledger.commands and store.read(anchor)==ARGS and custody.held


@pytest.mark.parametrize('point',['before_metadata','after_intent'])
def test_process_crash_retains_encrypted_payload_and_never_invents_settlement(tmp_path,point):
    from scripts.redis_append_custody import AppendStore
    segments=tmp_path/'segments';segments.mkdir();path=tmp_path/'ledger';head=tmp_path/'trusted-head'
    code="""
import os,sys
from pathlib import Path
from scripts.redis_append_custody import AppendStore
from scripts.redis_production_adapters import DurableJournal
j=DurableJournal(sys.argv[2]);s=AppendStore(sys.argv[1])
def save_head():
 with Path(sys.argv[3]).open('xb') as f:
  f.write(j.previous.encode());f.flush();os.fsync(f.fileno())
def persist(mark):
 if sys.argv[4]=='before_metadata':
  save_head();os._exit(73)
 j.persist_many([mark,{'stage':'COMMAND_INTENT','token':1,'state':'ISSUED'}])
s.prepare(1,[b'key',b'*',b'f',b'\\x00\\xff'],epoch='c'*40,journal=j,persist=persist)
save_head();os._exit(73)
"""
    result=subprocess.run([sys.executable,'-c',code,str(segments),str(path),str(head),point],timeout=10,capture_output=True)
    assert result.returncode==73,result.stderr
    records=read_records(path,expected_head=head.read_text());reader=AppendStore(segments,writable=False)
    try:
        assert reader.total>0
        if point=='before_metadata':
            assert records==[]
            with pytest.raises(AccountingError):reader.verify_inventory([],[])
        else:
            assert [r['stage'] for r in records]==['APPEND_CUSTODY','COMMAND_INTENT']
            assert records[-1]['state']=='ISSUED'  # Inspection, not dispatch/ACK authority.
            anchor=records[0]['anchor']
            assert reader.read(anchor)==[b'key',b'*',b'f',b'\x00\xff']
            assert reader.verify_inventory([anchor],[]) is True
    finally:reader.close()


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
