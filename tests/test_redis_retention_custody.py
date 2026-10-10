import copy
from types import SimpleNamespace

import pytest

from test_redis_evidence_archive import source
from scripts.redis_evidence_archive import EvidenceArchive, ArchivedRetention, proof_for
from scripts.redis_production_adapters import DurableJournal, ProductionAcknowledgements, read_records
from stinky_core.transport.redis_accounting import AccountingError, reply_bytes

OWNER={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}


@pytest.fixture
def custody(tmp_path):
    folder=tmp_path/'archive';folder.mkdir()
    state=source();state[1]=state[1][:1]
    client=SimpleNamespace(execute_command=lambda *a:copy.deepcopy(state))
    journal=DurableJournal(tmp_path/'ledger.jsonl')
    ledger=ProductionAcknowledgements(journal,['1-10-redis-streams'])
    ledger.register_connection('1-10-redis-streams',OWNER,11,'c'*40,1)
    token=ledger.begin_command('1-10-redis-streams','XADD',[b'key',b'*',b'f',b'\x00\xff',b'f',b'repeated'],11,1)
    ledger.complete_command(token,b'1-0',reply_bytes(b'1-0'),'original')
    boundary=ArchivedRetention(EvidenceArchive(folder),client,ledger,scope=lambda:'c'*40,
                               configuration={'maxmemory-policy':'noeviction'},expiring_keys=0)
    yield boundary,ledger,journal,state
    journal.close()


def trim(boundary):
    boundary.before('XADD',[b'key',b'MAXLEN',b'~',b'1',b'*',b'f',b'new'])


def test_custody_fsynced_and_verifiable_before_destructive_dispatch(custody):
    boundary,ledger,journal,state=custody
    trim(boundary)
    rows=read_records(journal.path,expected_head=journal.previous)
    assert rows[-1]['stage']=='RETENTION_CUSTODY' and rows[-1]['next_token']==2
    assert boundary.store.read(rows[-1]['anchor'])[0]==state
    # Redis is then allowed to remove the old entry. Actual prior bytes remain.
    full=state[1][0][-1];full[full.index(b'length')+1]=0;full[full.index(b'entries')+1]=[]
    assert boundary.verify(ledger,proof_for(state))['acknowledged']==1
    # The legacy gate remains strict. No globally relaxed membership policy.
    with pytest.raises(RuntimeError,match='missing'):
        ledger.verify(proof_for(state))


def test_unknown_reply_blocks_archive_and_retention(custody):
    boundary,ledger,journal,state=custody
    ledger.begin_command('1-10-redis-streams','LPUSH',[b'queue',b'unknown'],11,1)
    with pytest.raises(RuntimeError,match='Unresolved'):trim(boundary)
    assert boundary.held and not boundary.anchors


def test_archive_corruption_blocks_following_retention(custody):
    boundary,ledger,journal,state=custody;trim(boundary)
    blob=boundary.store.directory/boundary.anchors[0]['file'];blob.write_bytes(b'corrupt')
    with pytest.raises(AccountingError):trim(boundary)
    assert boundary.held and ledger.settled()==1


def test_late_custody_cannot_hide_prior_missing_receipt(custody):
    boundary,ledger,journal,state=custody
    full=state[1][0][-1];full[full.index(b'length')+1]=0;full[full.index(b'entries')+1]=[]
    with pytest.raises(AccountingError,match='absent'):trim(boundary)
    assert boundary.held


@pytest.mark.parametrize('form',[[b'key',b'MAXLEN',b'0',b'*',b'f',b'v'],
                               [b'key',b'MINID',b'1',b'*',b'f',b'v']])
def test_unsupported_retention_rejected_before_permission(custody,form):
    boundary,_,_,_=custody
    with pytest.raises(AccountingError):boundary.before('XADD',form)
    assert boundary.held and not boundary.anchors


def test_expiry_installation_is_explicitly_unsupported(custody):
    boundary,_,_,_=custody
    with pytest.raises(AccountingError,match='pre-dispatch'):boundary.before('SET',[b'key',b'value',b'EX',b'172800'])


def test_unaccounted_existing_expiry_blocks_retention(custody):
    boundary,_,_,state=custody;state[1][0][3]=400
    with pytest.raises(AccountingError,match='expiry'):trim(boundary)
    assert boundary.held


def test_partial_archive_does_not_authorize_retention(custody,monkeypatch):
    boundary,_,journal,_=custody
    def fail(record):raise OSError('anchor unavailable')
    monkeypatch.setattr(journal,'persist',fail)
    with pytest.raises(OSError):trim(boundary)
    assert boundary.held and not boundary.anchors
