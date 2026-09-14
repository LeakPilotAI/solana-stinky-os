from types import SimpleNamespace

import pytest

import stinky_api.dex_provenance_writer as writer


CHAIN = "base"
POOL = "0x1111111111111111111111111111111111111111"
BLOCK = 123


def record():
    return SimpleNamespace(
        relationship=SimpleNamespace(chain=CHAIN, pool_address=POOL, block_number=BLOCK)
    )


def sources():
    return (SimpleNamespace(chain=CHAIN),)


def install_codec(monkeypatch):
    monkeypatch.setattr(
        writer,
        "encode_reference_dex_evidence_record",
        lambda rec: {"schema": "GENESIS_DEX_PROVENANCE_EVIDENCE", "version": 1, "value": "record"},
    )
    monkeypatch.setattr(
        writer,
        "encode_reference_sources",
        lambda src: ({"schema": "GENESIS_DEX_PROVENANCE_EVIDENCE", "version": 1, "value": "source"},),
    )


def test_evidence_key_is_deterministic_and_requires_immutable_nonempty_sources(monkeypatch):
    install_codec(monkeypatch)
    rec = record()
    src = sources()

    first = writer.dex_provenance_evidence_key(rec, src)
    second = writer.dex_provenance_evidence_key(rec, src)

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64
    with pytest.raises(ValueError):
        writer.dex_provenance_evidence_key(rec, list(src))
    with pytest.raises(ValueError):
        writer.dex_provenance_evidence_key(rec, ())


@pytest.mark.asyncio
async def test_typed_writer_derives_identity_encodes_and_delegates_exactly(monkeypatch):
    install_codec(monkeypatch)
    rec = record()
    src = sources()
    validated = []
    appended = []

    def fake_validate(actual_record, *, chain, pool_address, evidence_block):
        validated.append((actual_record, chain, pool_address, evidence_block))

    async def fake_append(session, **kwargs):
        appended.append((session, kwargs))
        return 41

    monkeypatch.setattr(writer, "validate_record_identity", fake_validate)
    monkeypatch.setattr(writer, "append_dex_provenance_evidence", fake_append)

    session = object()
    row_id = await writer.persist_dex_provenance_evidence(session, record=rec, sources=src)

    assert row_id == 41
    assert validated == [(rec, CHAIN, POOL, BLOCK)]
    assert appended[0][0] is session
    kwargs = appended[0][1]
    assert kwargs["chain"] == CHAIN
    assert kwargs["pool_address"] == POOL
    assert kwargs["evidence_block"] == BLOCK
    assert kwargs["evidence_key"].startswith("sha256:")
    assert kwargs["record_payload"]["value"] == "record"
    assert kwargs["sources_payload"][0]["value"] == "source"


@pytest.mark.asyncio
async def test_typed_writer_fails_closed_on_inconsistent_identity_and_source_chain(monkeypatch):
    install_codec(monkeypatch)
    rec = record()

    def reject(*args, **kwargs):
        raise ValueError("identity mismatch")

    monkeypatch.setattr(writer, "validate_record_identity", reject)
    with pytest.raises(ValueError, match="identity mismatch"):
        await writer.persist_dex_provenance_evidence(object(), record=rec, sources=sources())

    monkeypatch.setattr(writer, "validate_record_identity", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="do not cover record chain"):
        await writer.persist_dex_provenance_evidence(
            object(), record=rec, sources=(SimpleNamespace(chain="ethereum"),)
        )


@pytest.mark.asyncio
async def test_typed_writer_rejects_mutable_or_empty_sources(monkeypatch):
    install_codec(monkeypatch)
    monkeypatch.setattr(writer, "validate_record_identity", lambda *args, **kwargs: None)
    rec = record()

    with pytest.raises(ValueError, match="immutable tuple"):
        await writer.persist_dex_provenance_evidence(object(), record=rec, sources=list(sources()))
    with pytest.raises(ValueError, match="must not be empty"):
        await writer.persist_dex_provenance_evidence(object(), record=rec, sources=())


@pytest.mark.asyncio
async def test_repeat_persist_uses_same_key_and_preserves_store_idempotence(monkeypatch):
    install_codec(monkeypatch)
    monkeypatch.setattr(writer, "validate_record_identity", lambda *args, **kwargs: None)
    seen_keys = []

    async def fake_append(session, **kwargs):
        seen_keys.append(kwargs["evidence_key"])
        return 77

    monkeypatch.setattr(writer, "append_dex_provenance_evidence", fake_append)
    rec = record()
    src = sources()

    first = await writer.persist_dex_provenance_evidence(object(), record=rec, sources=src)
    second = await writer.persist_dex_provenance_evidence(object(), record=rec, sources=src)

    assert first == second == 77
    assert len(seen_keys) == 2
    assert seen_keys[0] == seen_keys[1]
