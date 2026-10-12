import threading,time
from types import SimpleNamespace
import pytest
from scripts.redis_writer_broker import WriterBroker,RetentionBoundary
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements
from stinky_core.transport.redis_accounting import AccountingError

OWNER={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}

def test_failed_peer_publishes_hold_before_waiting_for_active_decision(tmp_path):
    journal=DurableJournal(tmp_path/'broker.jsonl');ledger=ProductionAcknowledgements(journal,['1-10-redis-streams'])
    revoked=[];credentials=SimpleNamespace(revoke_all=lambda:revoked.append(True))
    broker=WriterBroker(ledger,credentials,{1:OWNER},lambda p:OWNER,
                        RetentionBoundary({'maxmemory-policy':'noeviction'},0),
                        server_epoch='c'*40,endpoint='fixture')
    thread=None
    try:
        with broker.lock:
            thread=threading.Thread(target=broker.hold);thread.start()
            end=time.monotonic()+2
            while not broker.held and time.monotonic()<end:time.sleep(.001)
            assert broker.held and broker.fenced
            with pytest.raises(AccountingError,match='held'):
                broker.dispatch(1,{'sequence':1,'method':'settled','args':[]})
            assert not ledger.commands
        thread.join(2);assert not thread.is_alive() and revoked
    finally:
        if thread:thread.join(2)
        journal.close()


def test_credential_completion_cannot_cross_a_new_hold(tmp_path):
    journal=DurableJournal(tmp_path/'broker.jsonl');ledger=ProductionAcknowledgements(journal,['1-10-redis-streams'])
    revoked=[];broker=None
    def issue(*args):
        broker.held=True;broker.fenced=True
        return {'username':'synthetic-read-only-ticket'}
    credentials=SimpleNamespace(issue=issue,revoke_all=lambda:revoked.append(True))
    broker=WriterBroker(ledger,credentials,{1:OWNER},lambda p:OWNER,
                        RetentionBoundary({'maxmemory-policy':'noeviction'},0),
                        server_epoch='c'*40,endpoint='fixture')
    try:
        with pytest.raises(AccountingError,match='credential admission'):
            broker.dispatch(1,{'sequence':1,'method':'issue','args':[OWNER,'redis-streams',1,'c'*40]})
        assert broker.held and revoked and not ledger.commands
    finally:journal.close()
