from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from scripts.genesis_launch_provenance import encoded, signed
from scripts.genesis_redis_client_provenance import RedisClientObservations
from scripts.genesis_redis_registration_cohort import RegistrationCohort
from scripts.genesis_redis_pool_observation import PhysicalSession
from tests.test_genesis_child_observation import setup
from tests.test_genesis_redis_pool_observation import controller


def fixture():
    rows, parents, children, receiver, frame = setup('api')
    receiver.complete(children.accept('api', receiver.receive(frame)), lambda: True)
    children.confirm('api', receiver.completion)
    launches = children.client_launches()
    endpoint = {'container_id':'a'*64,'host':'127.0.0.1','port':16603}
    clients = [{'id':1,'name':'observer'}]
    registry = RedisClientObservations(launches, endpoint,
        lambda: {'endpoint':endpoint,'run_id':'b'*40,'clients':list(clients)}, {1},
        native_socket=lambda owner,socket: owner == rows[receiver.proof['body']['owner']['pid']])
    members = (('api','connection-1'),('api','connection-2'))
    cohort = RegistrationCohort(registry, launches, members, timeout=.5)
    challenges = cohort.prepare(); key = launches.checked('api')['key']
    proofs = {}
    for i, member in enumerate(members, 2):
        challenge = challenges[member]
        clients.append({'id':i,'name':challenge['expected_name']})
        proofs[member] = signed(key, {'kind':'genesis-redis-client-observation-v1',
            'challenge':challenge,'run_id':'b'*40,'client_id':i,'name':challenge['expected_name'],
            'socket':{'local_host':'127.0.0.1','local_port':20000+i,
                      'remote_host':'127.0.0.1','remote_port':16603}})
    return registry, cohort, clients, proofs, key, parents


def test_all_declared_connections_required_before_any_success():
    registry, cohort, clients, proofs, key, parents = fixture()
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(cohort.exchange,*member,proof) for member,proof in proofs.items()]
        for (member,proof), future in zip(proofs.items(),futures):
            session=PhysicalSession(key,proof['body']['challenge'],lambda _:None)
            session.receipt(proof,future.result())
    assert registry.audit()['status']=='ISOLATED_OBSERVATIONS_MATCH'
    assert cohort.phase=='OBSERVED'


@pytest.mark.parametrize('fault',['missing','foreign','duplicate-name','payload','retired','duplicate-proof'])
def test_cohort_faults_never_issue_matched_receipts(fault):
    registry, cohort, clients, proofs, key, parents = fixture()
    if fault=='foreign': clients.append({'id':99,'name':'foreign'})
    if fault=='duplicate-name': clients.append({'id':99,'name':clients[-1]['name']})
    if fault=='payload': next(iter(proofs.values()))['body']['client_id']=99
    if fault=='retired': parents.retire('api')
    items=list(proofs.items())
    if fault=='missing': items=items[:1]
    if fault=='duplicate-proof': items=[items[0],items[0]]
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(cohort.exchange,*m,p) for m,p in items]
        for future in futures:
            with pytest.raises(ValueError,match='HOLD'): future.result()
    assert cohort.phase=='HOLD' and not cohort.replies
    assert registry.audit()['status']=='HOLD'


def test_staging_is_not_a_matched_receipt():
    registry, cohort, clients, proofs, key, parents = fixture()
    member, proof=next(iter(proofs.items()))
    result=registry.stage(*member,proof)
    assert result['status']=='COLLECTING_NOT_ATTESTED'
    assert registry.audit()['status']=='HOLD'


def test_child_redis_binding_contains_no_supervisor_key():
    rows, parents, children, receiver, frame=setup()
    receiver.complete(children.accept('api',receiver.receive(frame)),lambda:True)
    children.confirm('api',receiver.completion)
    child=children.client_launches().checked('api')
    assert child['key'] != parents.checked('api')['key']
    assert child['challenge']['owner']['pid'] != parents.checked('api')['challenge']['owner']['pid']
    parents.retire('api')
    with pytest.raises(ValueError): children.client_launches().checked('api')


@pytest.mark.parametrize('asynchronous',[False,True])
def test_real_concurrent_physical_pool_registrations(controller, asynchronous):
    import asyncio
    factory, registry, endpoint = controller('api','api-manual-queue',asynchronous)
    launches=registry._launches
    key=launches.checked('api')['key']
    cohort=RegistrationCohort(registry,launches,
        (('api','api-manual-queue-1'),('api','api-manual-queue-2')),timeout=10)
    challenges=cohort.prepare()
    def prepare(role,slot):
        def exchange(proof): return cohort.exchange('api',slot,proof)
        async def async_exchange(proof): return await asyncio.to_thread(exchange,proof)
        return PhysicalSession(key,challenges[('api',slot)],async_exchange if asynchronous else exchange)
    factory.prepare=prepare
    clients=[factory.from_url(f"redis://127.0.0.1:{endpoint['port']}/0",role='api-manual-queue') for _ in range(2)]
    if asynchronous:
        async def run():
            try:
                try: results=await asyncio.gather(*(c.ping() for c in clients))
                except ValueError: raise AssertionError('Cohort stage: '+str(cohort.failure_stage)) from None
                assert all(results)
                assert cohort.phase=='OBSERVED' and registry.audit()['status']=='ISOLATED_OBSERVATIONS_MATCH'
                from scripts.genesis_redis_pool_observation import processed_receipt
                for client in clients:
                    for connection in client.connection_pool._available_connections:
                        slot=connection.observation.challenge['slot']
                        async def review(proof,s=slot):
                            return processed_receipt(key,proof,registry.review('api',s,proof))
                        connection.observation.exchange=review
                assert all(await asyncio.gather(*(c.ping() for c in clients)))
            finally:
                for client in clients: await client.aclose(); await client.connection_pool.disconnect()
        asyncio.run(run())
        return
    try:
        with ThreadPoolExecutor(2) as pool:
            assert all(f.result() for f in [pool.submit(client.ping) for client in clients])
        assert cohort.phase=='OBSERVED' and registry.audit()['status']=='ISOLATED_OBSERVATIONS_MATCH'
        # Reuse goes through fresh registry review, not the closed registration cohort.
        from scripts.genesis_redis_pool_observation import processed_receipt
        for client in clients:
            for connection in client.connection_pool._available_connections:
                slot=connection.observation.challenge['slot']
                connection.observation.exchange=lambda proof,s=slot: processed_receipt(key,proof,registry.review('api',s,proof))
        assert all(client.ping() for client in clients)
    finally:
        for client in clients: client.close(); client.connection_pool.disconnect()
