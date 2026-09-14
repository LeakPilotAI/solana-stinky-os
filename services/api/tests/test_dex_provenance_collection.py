from types import SimpleNamespace

import pytest

import stinky_api.dex_provenance_collection as collection


class Source:
    def __init__(self, reference):
        self.source_reference = reference


def sources():
    return (Source("ref-b"), Source("ref-a"))


def bundle():
    return SimpleNamespace(source_references=("ref-a", "ref-b"))


@pytest.mark.asyncio
async def test_collection_composes_once_and_persists_exact_record_and_source_tuple(monkeypatch):
    src = sources()
    evidence_bundle = bundle()
    relationship = object()
    factory_code = object()
    pool_code = object()
    router_code = object()
    composed_record = object()
    compose_calls = []
    persist_calls = []

    def fake_compose(actual_relationship, actual_factory, actual_pool, actual_router, actual_bundle):
        compose_calls.append(
            (actual_relationship, actual_factory, actual_pool, actual_router, actual_bundle)
        )
        return composed_record

    async def fake_persist(session, *, record, sources):
        persist_calls.append((session, record, sources))
        return 91

    monkeypatch.setattr(collection, "compose_reference_dex_evidence_record", fake_compose)
    monkeypatch.setattr(collection, "persist_dex_provenance_evidence", fake_persist)

    session = object()
    result = await collection.compose_and_persist_dex_provenance_evidence(
        session,
        relationship=relationship,
        factory_code=factory_code,
        pool_code=pool_code,
        router_code=router_code,
        bundle=evidence_bundle,
        sources=src,
    )

    assert compose_calls == [(relationship, factory_code, pool_code, router_code, evidence_bundle)]
    assert persist_calls == [(session, composed_record, src)]
    assert result.record is composed_record
    assert result.row_id == 91


@pytest.mark.asyncio
async def test_collection_does_not_persist_when_record_composition_fails(monkeypatch):
    persisted = []

    def fail_compose(*args, **kwargs):
        raise ValueError("incomplete evidence")

    async def fake_persist(*args, **kwargs):
        persisted.append((args, kwargs))
        return 1

    monkeypatch.setattr(collection, "compose_reference_dex_evidence_record", fail_compose)
    monkeypatch.setattr(collection, "persist_dex_provenance_evidence", fake_persist)

    with pytest.raises(ValueError, match="incomplete evidence"):
        await collection.compose_and_persist_dex_provenance_evidence(
            object(),
            relationship=object(),
            factory_code=object(),
            pool_code=object(),
            router_code=object(),
            bundle=bundle(),
            sources=sources(),
        )

    assert persisted == []


@pytest.mark.asyncio
async def test_collection_requires_exact_bundle_source_provenance_before_composition(monkeypatch):
    composed = []
    persisted = []

    def fake_compose(*args, **kwargs):
        composed.append(True)
        return object()

    async def fake_persist(*args, **kwargs):
        persisted.append(True)
        return 1

    monkeypatch.setattr(collection, "compose_reference_dex_evidence_record", fake_compose)
    monkeypatch.setattr(collection, "persist_dex_provenance_evidence", fake_persist)

    with pytest.raises(ValueError, match="do not match fingerprint bundle provenance"):
        await collection.compose_and_persist_dex_provenance_evidence(
            object(),
            relationship=object(),
            factory_code=object(),
            pool_code=object(),
            router_code=object(),
            bundle=SimpleNamespace(source_references=("different-ref",)),
            sources=sources(),
        )

    assert composed == []
    assert persisted == []


@pytest.mark.asyncio
async def test_collection_rejects_mutable_or_empty_sources_before_composition(monkeypatch):
    composed = []

    def fake_compose(*args, **kwargs):
        composed.append(True)
        return object()

    monkeypatch.setattr(collection, "compose_reference_dex_evidence_record", fake_compose)

    common = dict(
        relationship=object(),
        factory_code=object(),
        pool_code=object(),
        router_code=object(),
        bundle=bundle(),
    )

    with pytest.raises(ValueError, match="immutable tuple"):
        await collection.compose_and_persist_dex_provenance_evidence(
            object(), sources=list(sources()), **common
        )
    with pytest.raises(ValueError, match="must not be empty"):
        await collection.compose_and_persist_dex_provenance_evidence(
            object(), sources=(), **common
        )

    assert composed == []


@pytest.mark.asyncio
async def test_collection_surfaces_persistence_failure_without_recomposition(monkeypatch):
    composed_record = object()
    compose_count = 0

    def fake_compose(*args, **kwargs):
        nonlocal compose_count
        compose_count += 1
        return composed_record

    async def fail_persist(session, *, record, sources):
        assert record is composed_record
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(collection, "compose_reference_dex_evidence_record", fake_compose)
    monkeypatch.setattr(collection, "persist_dex_provenance_evidence", fail_persist)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await collection.compose_and_persist_dex_provenance_evidence(
            object(),
            relationship=object(),
            factory_code=object(),
            pool_code=object(),
            router_code=object(),
            bundle=bundle(),
            sources=sources(),
        )

    assert compose_count == 1
