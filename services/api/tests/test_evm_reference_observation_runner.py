from types import SimpleNamespace

import pytest

import stinky_api.evm_reference_observation_runner as runner


class Source:
    def __init__(self, chain, address, reference):
        self.chain = chain
        self.address = address
        self.source_reference = reference


def candidate():
    return SimpleNamespace(
        chain="ethereum-mainnet",
        factory_address="0xfactory",
        pool_address="0xpool",
    )


def rpc():
    return SimpleNamespace(chain=SimpleNamespace(key="ethereum-mainnet"))


@pytest.mark.asyncio
async def test_runner_propagates_exact_block_and_reuses_exact_sources(monkeypatch):
    pool = candidate()
    sources = (
        Source(pool.chain, pool.factory_address, "factory-ref"),
        Source(pool.chain, pool.pool_address, "pool-ref"),
        Source(pool.chain, "0xrouter", "router-ref"),
    )
    calls = []
    factory = SimpleNamespace(address=pool.factory_address)
    pool_code = SimpleNamespace(address=pool.pool_address)
    router = SimpleNamespace(address="0xrouter")
    relationship = SimpleNamespace(relationship="KNOWN_FACTORY_RELATIONSHIP")
    bundle = object()
    persisted = object()

    monkeypatch.setattr(runner, "canonical_chain_address", lambda chain, address: address)
    monkeypatch.setattr(runner, "observe_factory_contract_code", lambda observers, actual_pool, **kw: calls.append(("factory", kw)) or factory)
    monkeypatch.setattr(runner, "observe_pool_contract_code", lambda observers, actual_pool, **kw: calls.append(("pool", kw)) or pool_code)
    monkeypatch.setattr(runner, "observe_contract_code", lambda observers, **kw: calls.append(("router", kw)) or router)
    monkeypatch.setattr(runner, "build_factory_lookup", lambda actual_pool: "0xlookup")
    monkeypatch.setattr(runner, "observe_exact_call", lambda observers, **kw: calls.append(("lookup", kw)) or object())
    monkeypatch.setattr(runner, "classify_factory_relationship", lambda *args: relationship)

    def materialize(actual_sources, evidence, **kw):
        assert actual_sources is sources
        assert evidence == (factory, pool_code, router)
        assert kw["expected_block_numbers"] == {pool.chain: 123456}
        return bundle

    persisted_calls = []

    async def persist(session, **kw):
        persisted_calls.append((session, kw))
        return persisted

    monkeypatch.setattr(runner, "materialize_reference_fingerprint_bundle", materialize)
    monkeypatch.setattr(runner, "compose_and_persist_dex_provenance_evidence", persist)

    result = await runner.observe_and_persist_reference_dex_evidence(
        object(), pool=pool, router_address="0xrouter", sources=sources,
        observers=(rpc(), rpc()), block_number=123456, min_quorum=2,
    )

    assert [name for name, _ in calls] == ["factory", "pool", "router", "lookup"]
    assert all(kwargs["block_number"] == 123456 for _, kwargs in calls)
    assert all(kwargs["min_quorum"] == 2 for _, kwargs in calls)
    assert persisted_calls[0][1]["sources"] is sources
    assert persisted_calls[0][1]["bundle"] is bundle
    assert result.block_number == 123456
    assert result.persisted is persisted


@pytest.mark.asyncio
async def test_unknown_relationship_stops_before_materialization_or_persistence(monkeypatch):
    pool = candidate()
    sources = (Source(pool.chain, pool.factory_address, "factory-ref"),)
    factory = SimpleNamespace(address=pool.factory_address)
    pool_code = SimpleNamespace(address=pool.pool_address)
    router = SimpleNamespace(address="0xrouter")
    touched = []

    monkeypatch.setattr(runner, "canonical_chain_address", lambda chain, address: address)
    monkeypatch.setattr(runner, "observe_factory_contract_code", lambda *a, **k: factory)
    monkeypatch.setattr(runner, "observe_pool_contract_code", lambda *a, **k: pool_code)
    monkeypatch.setattr(runner, "observe_contract_code", lambda *a, **k: router)
    monkeypatch.setattr(runner, "build_factory_lookup", lambda pool: "0xlookup")
    monkeypatch.setattr(runner, "observe_exact_call", lambda *a, **k: object())
    monkeypatch.setattr(runner, "classify_factory_relationship", lambda *a: SimpleNamespace(relationship="UNKNOWN_FACTORY_RELATIONSHIP"))
    monkeypatch.setattr(runner, "materialize_reference_fingerprint_bundle", lambda *a, **k: touched.append("materialized"))

    async def persist(*a, **k):
        touched.append("persisted")

    monkeypatch.setattr(runner, "compose_and_persist_dex_provenance_evidence", persist)

    with pytest.raises(ValueError, match="unknown or insufficient"):
        await runner.observe_and_persist_reference_dex_evidence(
            object(), pool=pool, router_address="0xrouter", sources=sources,
            observers=(rpc(), rpc()), block_number=99,
        )
    assert touched == []


@pytest.mark.asyncio
async def test_known_conflict_is_preserved_and_handed_to_persistence(monkeypatch):
    pool = candidate()
    sources = (Source(pool.chain, pool.factory_address, "factory-ref"),)
    factory = SimpleNamespace(address=pool.factory_address)
    pool_code = SimpleNamespace(address=pool.pool_address)
    router = SimpleNamespace(address="0xrouter")
    conflict = SimpleNamespace(relationship="CONTRADICTORY_FACTORY_RELATIONSHIP")
    bundle = object()
    observed = []

    monkeypatch.setattr(runner, "canonical_chain_address", lambda chain, address: address)
    monkeypatch.setattr(runner, "observe_factory_contract_code", lambda *a, **k: factory)
    monkeypatch.setattr(runner, "observe_pool_contract_code", lambda *a, **k: pool_code)
    monkeypatch.setattr(runner, "observe_contract_code", lambda *a, **k: router)
    monkeypatch.setattr(runner, "build_factory_lookup", lambda pool: "0xlookup")
    monkeypatch.setattr(runner, "observe_exact_call", lambda *a, **k: object())
    monkeypatch.setattr(runner, "classify_factory_relationship", lambda *a: conflict)
    monkeypatch.setattr(runner, "materialize_reference_fingerprint_bundle", lambda *a, **k: bundle)

    async def persist(session, **kw):
        observed.append(kw["relationship"])
        return object()

    monkeypatch.setattr(runner, "compose_and_persist_dex_provenance_evidence", persist)
    result = await runner.observe_and_persist_reference_dex_evidence(
        object(), pool=pool, router_address="0xrouter", sources=sources,
        observers=(rpc(), rpc()), block_number=100,
    )
    assert observed == [conflict]
    assert result.relationship is conflict


@pytest.mark.asyncio
async def test_unobserved_or_mismatched_source_fails_before_observation(monkeypatch):
    pool = candidate()
    touched = []
    monkeypatch.setattr(runner, "canonical_chain_address", lambda chain, address: address)
    monkeypatch.setattr(runner, "observe_factory_contract_code", lambda *a, **k: touched.append(True))

    bad_address = (Source(pool.chain, "0xother", "other-ref"),)
    with pytest.raises(ValueError, match="outside the runner's observed DEX components"):
        await runner.observe_and_persist_reference_dex_evidence(
            object(), pool=pool, router_address="0xrouter", sources=bad_address,
            observers=(rpc(), rpc()), block_number=1,
        )

    bad_chain = (Source("base-mainnet", pool.factory_address, "wrong-chain"),)
    with pytest.raises(ValueError, match="share the pool chain"):
        await runner.observe_and_persist_reference_dex_evidence(
            object(), pool=pool, router_address="0xrouter", sources=bad_chain,
            observers=(rpc(), rpc()), block_number=1,
        )
    assert touched == []


@pytest.mark.asyncio
async def test_quorum_observation_failure_prevents_persistence(monkeypatch):
    pool = candidate()
    sources = (Source(pool.chain, pool.factory_address, "factory-ref"),)
    persisted = []
    monkeypatch.setattr(runner, "canonical_chain_address", lambda chain, address: address)

    def fail(*args, **kwargs):
        raise ValueError("provider disagreement")

    monkeypatch.setattr(runner, "observe_factory_contract_code", fail)

    async def persist(*args, **kwargs):
        persisted.append(True)

    monkeypatch.setattr(runner, "compose_and_persist_dex_provenance_evidence", persist)
    with pytest.raises(ValueError, match="provider disagreement"):
        await runner.observe_and_persist_reference_dex_evidence(
            object(), pool=pool, router_address="0xrouter", sources=sources,
            observers=(rpc(), rpc()), block_number=77,
        )
    assert persisted == []
