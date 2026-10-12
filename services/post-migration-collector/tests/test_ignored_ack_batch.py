import asyncio,json
import pytest
from post_migration.service import CollectorService
from post_migration.config import settings


def service(log, *, fail=False):
    s=object.__new__(CollectorService)
    class Redis:
        async def xack(self,stream,group,*ids):
            assert stream==settings.event_stream and group==settings.collector_consumer_group
            log.append(('ack',ids))
            if fail:raise ConnectionError('isolated lost batch reply')
            return len(ids)
    async def handle(identity,fields):log.append(('handle',identity))
    s._redis=Redis();s._handle_message=handle
    return s


def fields(kind):return {'data':json.dumps({'event_type':kind})}


def test_known_ignored_records_share_one_ack_without_relevant_side_effects():
    log=[];s=service(log)
    rows=[(str(n),fields('wallet.performance_updated')) for n in range(20)]
    asyncio.run(s._handle_batch(rows))
    assert log==[('ack',tuple(str(n) for n in range(20)))]


def test_relevant_unknown_and_malformed_records_preserve_handler_order():
    log=[];s=service(log)
    rows=[('1',fields('quality.state_changed')),('2',fields('token.migrated')),
          ('3',{'data':'malformed'}),('4',{'data':'{"payload":{}}'}),
          ('5',{'other':'{"event_type":"wallet.performance_updated"}'}),
          ('6',fields(None)),('7',fields('post_migration.tracking_started'))]
    asyncio.run(s._handle_batch(rows))
    assert log==[('handle','2'),('handle','3'),('handle','4'),
                 ('handle','5'),('handle','6'),('ack',('1','7'))]


def test_unexpected_oversized_delivery_fails_before_processing_or_ack():
    log=[];s=service(log)
    with pytest.raises(ValueError,match='COUNT 20'):
        asyncio.run(s._handle_batch([(str(n),fields('wallet.performance_updated')) for n in range(21)]))
    assert log==[]


def test_lost_ignored_ack_reply_cannot_strand_a_delivered_migration_and_is_not_retried():
    log=[];s=service(log,fail=True)
    with pytest.raises(ConnectionError):
        asyncio.run(s._handle_batch([('1',fields('wallet.performance_updated')),('2',fields('token.migrated'))]))
    assert log==[('handle','2'),('ack',('1',))]


def test_replayed_ignored_records_are_only_acknowledged_again():
    log=[];s=service(log);rows=[('1',fields('wallet.performance_updated'))]
    asyncio.run(s._handle_batch(rows));asyncio.run(s._handle_batch(rows))
    assert log==[('ack',('1',)),('ack',('1',))]


@pytest.mark.parametrize('applied_before_lost_reply',[False,True])
def test_real_migration_handlers_finish_in_order_before_ambiguous_noop_ack(applied_before_lost_reply):
    s=object.__new__(CollectorService);log=[];pending={'1','2','3','4'}
    class Redis:
        async def xack(self,stream,group,*ids):
            log.append(('ack',ids))
            if ids==('1','3'):
                if applied_before_lost_reply:pending.difference_update(ids)
                raise ConnectionError('isolated lost no-op batch reply')
            pending.difference_update(ids);return len(ids)
    async def migration(event,payload):log.append(('migration',payload['identity']))
    s._redis=Redis();s._on_migration=migration
    rows=[('1',fields('wallet.performance_updated')),
          ('2',{'data':json.dumps({'event_type':'token.migrated','payload':{'identity':'first'}})}),
          ('3',fields('quality.state_changed')),
          ('4',{'payload':json.dumps({'event':{'type':'token.migrated','payload':{'identity':'second'}}})})]
    with pytest.raises(ConnectionError):asyncio.run(s._handle_batch(rows))
    assert log==[('migration','first'),('ack',('2',)),('migration','second'),('ack',('4',)),('ack',('1','3'))]
    assert pending==(set() if applied_before_lost_reply else {'1','3'})


def test_cancellation_during_relevant_processing_never_acknowledges_unfinished_work():
    log=[];s=service(log)
    async def cancel(identity,fields):raise asyncio.CancelledError()
    s._handle_message=cancel
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(s._handle_batch([('1',fields('wallet.performance_updated')),('2',fields('token.migrated'))]))
    assert log==[]
