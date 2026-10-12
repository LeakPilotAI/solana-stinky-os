import copy
from types import SimpleNamespace
import pytest
from scripts.redis_append_custody import FixedReadonlyEntryProbe,OBSERVE
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from test_redis_append_custody import fixture,apply,ARGS,WRITER,EPOCH


class Probe:
    def __init__(self,rows):self.rows=rows;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def info(self,*args):self.calls.append(('INFO',*args));return self
    def execute_command(self,*args):self.calls.append(args);return self
    def execute(self):return copy.deepcopy(self.rows)


def client(probe):
    def pipeline(*,transaction):assert transaction is False;return probe
    return SimpleNamespace(pipeline=pipeline)


def test_readonly_probe_keeps_both_remote_epochs_and_exact_ordered_bytes():
    entries=[[b'2-0',[b'f',b'\x00\xff',b'f',b'duplicate']]]
    p=Probe([{'run_id':EPOCH},entries,{'run_id':EPOCH}])
    assert FixedReadonlyEntryProbe(client(p))(b'key','2-0')==(EPOCH,entries,EPOCH)
    assert p.calls==[('INFO','server'),('EVAL_RO',OBSERVE,1,b'key','2-0'),('INFO','server')]


@pytest.mark.parametrize('bad',['before','after','payload','order','missing','malformed','partial'])
def test_combined_observation_cannot_settle_missing_or_contradictory_evidence(fixture,bad):
    store,custody,ledger,journal,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1);apply(state,b'2-0',ARGS[5:])
    rows=[{'run_id':EPOCH},[[b'2-0',ARGS[5:]]],{'run_id':EPOCH}]
    if bad=='before':rows[0]['run_id']='d'*40
    if bad=='after':rows[2]['run_id']='d'*40
    if bad=='payload':rows[1][0][1]=[b'f',b'changed']
    if bad=='order':rows[1][0][1]=[b'f',b'duplicate',b'f',b'\x00\xff']
    if bad=='missing':rows[1]=[]
    if bad=='malformed':rows[0]={}
    if bad=='partial':rows.pop()
    custody.entry_probe=FixedReadonlyEntryProbe(client(Probe(rows)))
    with pytest.raises(AccountingError):ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    assert custody.held and ledger.commands[token]['state']=='ISSUED' and token not in custody.observed
    assert store.read(store.records[token])==ARGS


def test_corrupt_ciphertext_is_checked_even_when_observer_reply_matches(fixture):
    store,custody,ledger,journal,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    custody.entry_probe=FixedReadonlyEntryProbe(client(Probe([{'run_id':EPOCH},[[b'2-0',ARGS[5:]]],{'run_id':EPOCH}])))
    anchor=store.records[token];path=store.directory/anchor['file']
    with path.open('r+b') as stream:
        stream.seek(anchor['offset']+4);stream.write(b'corrupt')
    with pytest.raises(AccountingError):ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    assert ledger.commands[token]['state']=='ISSUED' and custody.held
