from types import SimpleNamespace

import pytest

from scripts.redis_broker_recovery import recover_held_boundary
from scripts.redis_production_adapters import DurableJournal, ProductionAcknowledgements, writer_id
from scripts.redis_writer_broker import WriterBroker, RetentionBoundary
from stinky_core.transport.redis_accounting import AccountingError, reply_bytes

OWNER = {'pid': 1, 'creation_ticks': 10, 'service': 'fixture',
         'command_sha256': 'a' * 64, 'repository_sha256': 'b' * 64}


def source(tmp_path, *, acknowledge=True):
    journal = DurableJournal(tmp_path / 'before.jsonl')
    writer = writer_id(OWNER, 'redis-streams')
    ledger = ProductionAcknowledgements(journal, [writer])
    broker = WriterBroker(ledger, SimpleNamespace(), {1: OWNER}, lambda pid: OWNER,
                         RetentionBoundary({'maxmemory-policy': 'noeviction'}, 0),
                         server_epoch='c' * 40, endpoint='original')
    journal.persist({'stage': 'CONNECTION_CREDENTIAL_ISSUED', 'principal': 'genesis-c66-' + 'd' * 32,
                     'owner': OWNER, 'role': 'redis-streams', 'generation': 1, 'server_epoch': 'c' * 40})
    ledger.register_connection(writer, OWNER, 11, 'c' * 40, 1)
    token = ledger.begin_command(writer, 'LPUSH', [b'queue', b'one'], 11, 1)
    if acknowledge:
        ledger.complete_command(token, 1, reply_bytes(1), 'original')
    return journal, broker, writer


@pytest.mark.parametrize('acknowledge', [True, False])
def test_restart_preserves_every_intent_revokes_and_never_resumes(tmp_path, acknowledge):
    previous, broker, writer = source(tmp_path, acknowledge=acknowledge)
    head = previous.previous; previous.close()
    next_journal = DurableJournal(tmp_path / 'recovered.jsonl'); revoked = []
    try:
        recovered = recover_held_boundary(previous.path, expected_head=head, next_journal=next_journal,
                                          revoke=revoked.append, verify_revoked=lambda p: p in revoked)
        assert recovered['held'] and recovered['fenced'] and recovered['next_generation'] == 2
        ledger = recovered['ledger']
        assert ledger.commands == broker.ledger.commands
        assert revoked == ['genesis-c66-' + 'd' * 32]
        assert not any(b['active'] for b in ledger.bindings.values())
        with pytest.raises(AccountingError):
            ledger.begin_command(writer, 'LPUSH', [b'queue', b'two'], 11, 1)
        with pytest.raises(AccountingError):
            ledger.register_connection(writer, OWNER, 12, 'c' * 40, 2)
        with pytest.raises(TypeError):
            ledger.commands[1]['state'] = 'ACKNOWLEDGED'
        if acknowledge:
            assert ledger.settled() == 1
        else:
            with pytest.raises(RuntimeError, match='Unresolved'):
                ledger.settled()
    finally:
        next_journal.close()


def test_repeated_crash_recovery_uses_preserved_original_anchor_and_remains_held(tmp_path):
    previous, _, _ = source(tmp_path, acknowledge=False)
    head = previous.previous; previous.close()
    for attempt in range(2):
        next_journal = DurableJournal(tmp_path / f'recovered-{attempt}.jsonl')
        try:
            recovered = recover_held_boundary(previous.path, expected_head=head, next_journal=next_journal,
                                              revoke=lambda p: None, verify_revoked=lambda p: True)
            assert recovered['held'] and recovered['ledger'].commands[1]['state'] == 'ISSUED'
        finally:
            next_journal.close()


@pytest.mark.parametrize('kind', ['lost_tail', 'corrupt', 'missing_anchor', 'wrong_anchor'])
def test_untrusted_recovery_never_performs_route_or_revocation(tmp_path, kind):
    previous, _, _ = source(tmp_path); head = previous.previous; previous.close()
    data = previous.path.read_bytes()
    if kind == 'lost_tail':
        previous.path.write_bytes(b'\n'.join(data.splitlines()[:-1]) + b'\n')
    elif kind == 'corrupt':
        previous.path.write_bytes(data.replace(b'original', b'changed!'))
    elif kind == 'missing_anchor':
        head = None
    else:
        head = 'f' * 64
    next_journal = DurableJournal(tmp_path / 'recovered.jsonl'); revoked = []
    try:
        with pytest.raises(AccountingError):
            recover_held_boundary(previous.path, expected_head=head, next_journal=next_journal,
                                  revoke=revoked.append, verify_revoked=lambda p: True)
        assert not revoked and next_journal.sequence == 0
    finally:
        next_journal.close()


@pytest.mark.parametrize('failure', ['revoke', 'verification', 'journal'])
def test_partial_recovery_failure_cannot_claim_success(tmp_path, failure):
    previous, _, _ = source(tmp_path); head = previous.previous; previous.close()
    next_journal = DurableJournal(tmp_path / 'recovered.jsonl')
    def revoke(principal):
        if failure == 'revoke':
            raise OSError('authority unavailable')
    if failure == 'journal':
        next_journal.failed = True
    try:
        with pytest.raises((AccountingError, OSError)):
            recover_held_boundary(previous.path, expected_head=head, next_journal=next_journal,
                                  revoke=revoke, verify_revoked=lambda p: failure != 'verification')
        assert next_journal.sequence == 0
    finally:
        next_journal.close()


@pytest.mark.parametrize('kind', ['changed_reply', 'unknown_stage', 'second_route', 'stale_generation'])
def test_semantic_contradictions_rejected_even_with_valid_hash_chain(tmp_path, kind):
    previous, _, _ = source(tmp_path)
    if kind == 'unknown_stage':
        previous.persist({'stage': 'UNREGISTERED_WRITE'})
    elif kind == 'second_route':
        previous.persist({'stage': 'BROKER_ROUTE'})
    elif kind == 'stale_generation':
        previous.persist({'stage': 'CONNECTION_REGISTERED', 'writer': '1-10-redis-streams',
                          'owner': OWNER, 'client_id': 12, 'generation': 2,
                          'server_epoch': 'c' * 40, 'active': True})
    else:
        previous.persist({'stage': 'COMMAND_REPLY', 'token': 1, 'state': 'ACKNOWLEDGED'})
    head = previous.previous; previous.close(); next_journal = DurableJournal(tmp_path / 'recovered.jsonl')
    try:
        with pytest.raises(AccountingError):
            recover_held_boundary(previous.path, expected_head=head, next_journal=next_journal,
                                  revoke=lambda p: None, verify_revoked=lambda p: True)
    finally:
        next_journal.close()
