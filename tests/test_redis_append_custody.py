import copy
from types import SimpleNamespace

import pytest

from scripts.redis_append_custody import AppendStore, AppendCustody, OBSERVE
from scripts.redis_evidence_archive import EvidenceArchive, proof_for
from scripts.redis_production_adapters import DurableJournal, ProductionAcknowledgements, read_records
from stinky_core.transport.redis_accounting import AccountingError, reply_bytes
from test_redis_evidence_archive import source

OWNER = {'pid': 1, 'creation_ticks': 10, 'service': 'fixture',
         'command_sha256': 'a'*64, 'repository_sha256': 'b'*64}
WRITER = '1-10-redis-streams'
EPOCH = 'c'*40
ARGS = [b'key', b'MAXLEN', b'=', b'1', b'*', b'f', b'\x00\xff', b'f', b'duplicate']


@pytest.fixture
def fixture(tmp_path):
    segment_dir = tmp_path/'segments'; segment_dir.mkdir()
    base_dir = tmp_path/'base'; base_dir.mkdir()
    state = source(); state[1] = state[1][:1]
    def execute(*args):
        if args[1] == OBSERVE:
            full = state[1][0][-1]
            return [r for r in full[full.index(b'entries')+1] if r[0] == args[-1].encode()]
        return copy.deepcopy(state)
    journal = DurableJournal(tmp_path/'ledger.jsonl')
    journal.persist({'stage':'BROKER_ROUTE','server_epoch':EPOCH,'endpoint':'fixture',
                     'generation':1,'manifest':[OWNER],'writers':[WRITER]})
    ledger = ProductionAcknowledgements(journal, [WRITER])
    ledger.register_connection(WRITER, OWNER, 11, EPOCH, 1)
    store = AppendStore(segment_dir)
    custody = AppendCustody(store, EvidenceArchive(base_dir), SimpleNamespace(execute_command=execute),
                            ledger, scope=lambda:EPOCH,
                            configuration={'maxmemory-policy':'noeviction'}, expiring_keys=0)
    ledger.custody = custody
    yield store, custody, ledger, journal, state
    store.close(); journal.close()


def apply(state, entry_id, fields):
    full = state[1][0][-1]
    for name, value in ((b'entries', [[entry_id, fields]]), (b'length', 1),
                        (b'last-generated-id', entry_id), (b'recorded-first-entry-id', entry_id)):
        full[full.index(name)+1] = value
    full[full.index(b'entries-added')+1] += 1


def test_observed_records_survive_trim_with_one_base_snapshot(fixture):
    store, custody, ledger, journal, state = fixture
    for n in range(1, 151):
        token = ledger.begin_command(WRITER, 'XADD', ARGS, 11, 1)
        entry_id = f'{n+1}-0'.encode()
        apply(state, entry_id, ARGS[5:])
        ledger.complete_command(token, entry_id, reply_bytes(entry_id), 'fixture')
    assert len(list(custody.base_archive.directory.iterdir())) == 1
    assert store.count == 1 and len(store.records) == 150
    assert ledger.verify(proof_for(state))['observed_append_records'] == 150
    assert b'duplicate' not in next(store.directory.iterdir()).read_bytes()
    rows = read_records(journal.path, expected_head=journal.previous)
    assert sum(r['stage']=='CUSTODY_OBSERVED' for r in rows) == 150


def test_only_actual_exact_entry_can_settle_receipt(fixture):
    store, custody, ledger, journal, state = fixture
    token = ledger.begin_command(WRITER, 'XADD', ARGS, 11, 1)
    apply(state, b'2-0', [b'f', b'altered'])
    with pytest.raises(AccountingError, match='Actual Redis'):
        ledger.complete_command(token, b'2-0', reply_bytes(b'2-0'), 'fixture')
    assert custody.held and ledger.commands[token]['state'] == 'ISSUED'
    assert store.read(store.records[token]) == ARGS
    with pytest.raises(RuntimeError, match='Unresolved'):ledger.settled()


def test_duplicate_prepare_does_not_repeat_storage_or_dispatch(fixture):
    store, _, _, journal, _ = fixture
    first = store.prepare(1, ARGS, epoch=EPOCH, journal=journal)
    before = journal.previous, store.total
    assert store.prepare(1, ARGS, epoch=EPOCH, journal=journal) == first
    assert (journal.previous, store.total) == before
    with pytest.raises(AccountingError, match='contradicts'):
        store.prepare(1, ARGS[:-1]+[b'corrupt'], epoch=EPOCH, journal=journal)
    assert store.held


def test_segment_handoff_is_anchored_before_new_segment(tmp_path):
    root = tmp_path/'store'; root.mkdir()
    journal = DurableJournal(tmp_path/'anchors.jsonl')
    store = AppendStore(root, segment_bytes=1024)
    try:
        anchors = [store.prepare(n, ARGS, epoch=EPOCH, journal=journal) for n in range(1,5)]
        assert store.count > 1 and store.seals
        rows = read_records(journal.path, expected_head=journal.previous)
        first_seal = next(i for i,r in enumerate(rows) if r['stage']=='CUSTODY_SEGMENT_SEALED')
        assert rows[first_seal+1]['stage']=='APPEND_CUSTODY'
        assert rows[first_seal+1]['anchor']['file'] != rows[first_seal]['file']
        assert rows[first_seal]['bytes'] == (root/rows[first_seal]['file']).stat().st_size
        for anchor in anchors:assert store.read(anchor) == ARGS
        store.seal(journal)
        reader = AppendStore(root, writable=False, segment_bytes=1024)
        for anchor in anchors:assert reader.read(anchor) == ARGS
        with pytest.raises(AccountingError, match='held recovery'):
            AppendStore(root, segment_bytes=1024)
    finally:store.close(); journal.close()


def test_exhaustion_retains_data_and_refuses_before_intent(tmp_path):
    root = tmp_path/'store'; root.mkdir()
    journal = DurableJournal(tmp_path/'anchors.jsonl')
    store = AppendStore(root, segment_bytes=1024, max_segments=1)
    try:
        first = store.prepare(1, ARGS, epoch=EPOCH, journal=journal)
        token = 2
        while store.size + first['bytes'] + 4 <= store.segment_bytes:
            store.prepare(token, ARGS, epoch=EPOCH, journal=journal)
            token += 1
        with pytest.raises(AccountingError, match='exhausted'):
            store.prepare(token, ARGS, epoch=EPOCH, journal=journal)
        assert store.held and store.read(first) == ARGS
        assert not any(r['stage']=='COMMAND_INTENT' for r in read_records(journal.path,expected_head=journal.previous))
    finally:store.close(); journal.close()


def test_lost_anchor_write_holds_and_retains_unanchored_record(fixture, monkeypatch):
    store, _, _, journal, _ = fixture
    def failed(record):raise OSError('durability unavailable')
    monkeypatch.setattr(journal, 'persist', failed)
    with pytest.raises(OSError):store.prepare(1, ARGS, epoch=EPOCH, journal=journal)
    assert store.held and len(list(store.directory.iterdir()))==1 and not store.records


@pytest.mark.parametrize('kind', ['corrupt', 'truncate', 'wrong_offset', 'wrong_token'])
def test_custody_corruption_never_recovers_as_success(fixture, kind):
    store, _, _, journal, _ = fixture
    anchor = store.prepare(1, ARGS, epoch=EPOCH, journal=journal)
    path = store.directory/anchor['file']
    if kind=='corrupt':
        raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
    elif kind=='truncate':path.write_bytes(path.read_bytes()[:-1])
    elif kind=='wrong_offset':anchor={**anchor,'offset':1}
    else:anchor={**anchor,'token':2}
    with pytest.raises(AccountingError):store.read(anchor)


@pytest.mark.parametrize('name,args', [('SET',[b'key',b'value',b'EX',b'1']),
    ('BRPOP',[b'queue',b'1']), ('XADD',[b'key',b'MAXLEN',b'0',b'*',b'f',b'v']),
    ('XADD',[b'key',b'MINID',b'1',b'*',b'f',b'v'])])
def test_unsupported_retention_and_pop_cannot_dispatch(fixture, name, args):
    store, custody, ledger, _, _ = fixture
    with pytest.raises(AccountingError):ledger.begin_command(WRITER,name,args,11,1)
    assert not ledger.commands and not store.records


def test_recovery_preserves_observed_records_and_requires_explicit_authorization(fixture, tmp_path):
    from scripts.redis_broker_recovery import recover_held_boundary
    store,custody,ledger,journal,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    apply(state,b'2-0',ARGS[5:]);ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    store.seal(journal)
    head=journal.previous
    recovered_journal=DurableJournal(tmp_path/'held.jsonl')
    reader=AppendStore(store.directory,writable=False)
    try:
        recovered=recover_held_boundary(journal.path,expected_head=head,next_journal=recovered_journal,
            revoke=lambda p:None,verify_revoked=lambda p:True,
            verify_archive=lambda a:custody.base_archive.read(a) is not None,
            read_append=reader.read,verify_append_inventory=reader.verify_inventory)
        assert recovered['held'] and recovered['fenced'] and recovered['ledger'].settled()==1
        assert recovered['observed_appends'][1]['entry_id']=='2-0'
        assert reader.read(recovered['append_anchors'][1])==ARGS
        with pytest.raises(AccountingError,match='held'):
            recovered['ledger'].begin_command(WRITER,'XADD',ARGS,11,1)
    finally:recovered_journal.close()


def test_crash_inflight_keeps_payload_and_unknown_receipt(fixture, tmp_path):
    from scripts.redis_broker_recovery import recover_held_boundary
    store,custody,ledger,journal,state=fixture
    ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    apply(state,b'2-0',ARGS[5:])  # Accepted by Redis, reply not settled.
    store.close();reader=AppendStore(store.directory,writable=False)
    held=DurableJournal(tmp_path/'held.jsonl')
    try:
        recovered=recover_held_boundary(journal.path,expected_head=journal.previous,next_journal=held,
            revoke=lambda p:None,verify_revoked=lambda p:True,
            verify_archive=lambda a:custody.base_archive.read(a) is not None,
            read_append=reader.read,verify_append_inventory=reader.verify_inventory)
        assert reader.read(recovered['append_anchors'][1])==ARGS
        assert not recovered['observed_appends']
        with pytest.raises(RuntimeError,match='Unresolved'):recovered['ledger'].settled()
    finally:held.close()


def test_unanchored_tail_and_missing_records_cannot_be_discarded(fixture):
    store,_,_,journal,_=fixture
    first=store.prepare(1,ARGS,epoch=EPOCH,journal=journal)
    second=store.prepare(2,ARGS,epoch=EPOCH,journal=journal)
    store.close();reader=AppendStore(store.directory,writable=False)
    assert reader.verify_inventory([first,second],[]) is True
    with pytest.raises(AccountingError):reader.verify_inventory([second],[])
    with (store.directory/second['file']).open('ab') as f:f.write(b'unanchored')
    with pytest.raises(AccountingError,match='Unaccounted'):
        reader.verify_inventory([first,second],[])


def test_current_corruption_is_not_hidden_by_correct_custody(fixture):
    _,_,ledger,_,state=fixture
    token=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    apply(state,b'2-0',ARGS[5:]);ledger.complete_command(token,b'2-0',reply_bytes(b'2-0'),'fixture')
    apply(state,b'2-0',[b'f',b'corrupt'])
    with pytest.raises(AccountingError,match='contradicts'):ledger.verify(proof_for(state))


def test_competing_mutation_has_known_pre_intent_backpressure(fixture):
    from stinky_core.transport.redis_accounting import DispatchBusy
    store,_,ledger,journal,_=fixture
    ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    head=journal.previous
    with pytest.raises(DispatchBusy):ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    assert journal.previous==head and len(ledger.commands)==1 and len(store.records)==1


def test_explicit_uncertainty_cannot_be_later_settled_or_bypassed(fixture):
    _,_,ledger,_,_=fixture
    token=ledger.begin_command(WRITER,'LPUSH',[b'queue',b'unknown'],11,1)
    ledger.mark_uncertain(token,'fixture')
    with pytest.raises(AccountingError,match='Uncertain'):ledger.complete_command(token,1,reply_bytes(1),'fixture')
    with pytest.raises(AccountingError,match='Unresolved'):ledger.settled()
    with pytest.raises(AccountingError,match='Uncertain'):ledger.begin_command(WRITER,'LPUSH',[b'queue',b'new'],11,1)


def test_duplicate_entry_id_cannot_reuse_prior_acknowledgement(fixture):
    _,_,ledger,_,state=fixture
    first=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    apply(state,b'2-0',ARGS[5:]);ledger.complete_command(first,b'2-0',reply_bytes(b'2-0'),'fixture')
    second=ledger.begin_command(WRITER,'XADD',ARGS,11,1)
    with pytest.raises(AccountingError,match='Duplicate'):
        ledger.complete_command(second,b'2-0',reply_bytes(b'2-0'),'fixture')
    assert ledger.commands[second]['state']=='ISSUED'
