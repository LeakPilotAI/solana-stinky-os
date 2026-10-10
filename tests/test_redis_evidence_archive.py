import copy
from types import SimpleNamespace

import pytest

from scripts import redis_evidence_archive as archive
from scripts.redis_stream_integrity import framed_hash
from stinky_core.transport.redis_accounting import AccountingError


def source():
    consumer = [b'name', b'alice', b'seen-time', 100, b'active-time', 100,
                b'pel-count', 1, b'pending', [[b'1-0', 90, 2]]]
    group = [b'name', b'group', b'last-delivered-id', b'1-0', b'entries-read', 1,
             b'lag', 0, b'pel-count', 1, b'pending', [[b'1-0', b'alice', 90, 2]],
             b'consumers', [consumer]]
    full = [b'length', 1, b'radix-tree-keys', 1, b'radix-tree-nodes', 2,
            b'last-generated-id', b'1-0', b'max-deleted-entry-id', b'0-0',
            b'entries-added', 1, b'recorded-first-entry-id', b'1-0',
            b'entries', [[b'1-0', [b'f', b'\x00\xff', b'f', b'repeated']]], b'groups', [group]]
    return [200, [[b'key', b'stream', b'actual-dump-bytes', -1, full],
                  [b'expiring', b'string', b'actual-value-dump', 400, []]]]


@pytest.fixture
def boundary(tmp_path):
    store = archive.EvidenceArchive(tmp_path)
    raw = source()
    anchors = []
    anchor = store.capture(SimpleNamespace(execute_command=lambda *args: copy.deepcopy(raw)),
                           scope=lambda: 'a' * 40, journal_head='b' * 64,
                           persist_anchor=anchors.append)
    return store, raw, anchors, anchor


def test_actual_bytes_metadata_and_expiry_survive_protected_readback(boundary):
    store, raw, anchors, anchor = boundary
    restored, proof = store.read(anchor)
    assert restored == raw and anchors == [anchor]
    assert b'actual-dump-bytes' not in (store.directory / anchor['file']).read_bytes()
    key = next(k for k in proof['keys'] if k['type'] == 'stream')
    assert key['stable']['groups'][0]['pending'][0]['delivery_count'] == 2
    assert store.require_receipt(anchor, key_sha256=archive.digest(b'key'), entry_id='1-0',
                                 payload_sha256=framed_hash([b'f', b'\x00\xff', b'f', b'repeated']),
                                 field_count=2)


@pytest.mark.parametrize('field,value', [('entry_id', '2-0'), ('payload_sha256', 'f' * 64),
                                      ('key_sha256', 'c' * 64), ('field_count', 1)])
def test_missing_or_corrupted_historical_receipt_rejected(boundary, field, value):
    store, _, _, anchor = boundary
    args = dict(key_sha256=archive.digest(b'key'), entry_id='1-0',
                payload_sha256=framed_hash([b'f', b'\x00\xff', b'f', b'repeated']), field_count=2)
    args[field] = value
    with pytest.raises(AccountingError):
        store.require_receipt(anchor, **args)


@pytest.mark.parametrize('failure', ['truncate', 'corrupt', 'missing', 'wrong_anchor', 'wrong_plaintext'])
def test_archive_integrity_failures_never_become_empty_success(boundary, failure):
    store, _, _, anchor = boundary
    path = store.directory / anchor['file']
    if failure == 'truncate':
        path.write_bytes(path.read_bytes()[:-1])
    elif failure == 'corrupt':
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
    elif failure == 'missing':
        anchor = {**anchor, 'file': 'f' * 32 + '.dpapi'}
    elif failure == 'wrong_anchor':
        anchor = {**anchor, 'ciphertext_sha256': 'f' * 64}
    else:
        anchor = {**anchor, 'plaintext_sha256': 'f' * 64}
    with pytest.raises((AccountingError, FileNotFoundError)):
        store.read(anchor)


def test_failed_external_anchor_retains_blob_but_returns_no_success(tmp_path):
    store = archive.EvidenceArchive(tmp_path)
    def failed(anchor):
        raise OSError('durable anchor unavailable')
    with pytest.raises(OSError):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=failed)
    assert len(list(tmp_path.glob('*.dpapi'))) == 1


def test_fsync_failure_does_not_publish_anchor(tmp_path, monkeypatch):
    store = archive.EvidenceArchive(tmp_path); anchors = []
    def failed(fd):
        raise OSError('disk failure')
    monkeypatch.setattr(archive.os, 'fsync', failed)
    with pytest.raises(OSError):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=anchors.append)
    assert not anchors and len(list(tmp_path.glob('*.dpapi'))) == 1


def test_changed_source_epoch_blocks_archive_before_disk_write(tmp_path):
    store = archive.EvidenceArchive(tmp_path); epochs = iter(['a' * 40, 'c' * 40])
    with pytest.raises(AccountingError):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: next(epochs),
                      journal_head='b' * 64, persist_anchor=lambda a: None)
    assert not list(tmp_path.iterdir())


def test_late_archive_cannot_reconstruct_already_trimmed_payload(tmp_path):
    raw = source(); full = raw[1][0][-1]
    full[full.index(b'entries') + 1] = []
    full[full.index(b'length') + 1] = 0
    # Pending metadata refers to a removed ID; it does not contain its bytes.
    store = archive.EvidenceArchive(tmp_path)
    anchor = store.capture(SimpleNamespace(execute_command=lambda *a: raw), scope=lambda: 'a' * 40,
                           journal_head='b' * 64, persist_anchor=lambda a: None)
    with pytest.raises(AccountingError):
        store.require_receipt(anchor, key_sha256=archive.digest(b'key'), entry_id='1-0',
                              payload_sha256=framed_hash([b'f', b'\x00\xff', b'f', b'repeated']), field_count=2)


def test_duplicate_capture_keeps_both_boundaries_without_overwrite(tmp_path):
    store = archive.EvidenceArchive(tmp_path); anchors = []
    for _ in range(2):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=anchors.append)
    assert len(list(tmp_path.iterdir())) == 2 and anchors[0]['file'] != anchors[1]['file']


def test_disconnected_source_does_not_publish_fabricated_archive(tmp_path):
    store = archive.EvidenceArchive(tmp_path)
    def offline(*args):
        raise ConnectionError('offline')
    with pytest.raises(ConnectionError):
        store.capture(SimpleNamespace(execute_command=offline), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=lambda a: None)
    assert not list(tmp_path.iterdir())


def test_archive_count_budget_fails_before_source_read_without_deleting_evidence(tmp_path):
    store = archive.EvidenceArchive(tmp_path, max_archives=1)
    store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                  journal_head='b' * 64, persist_anchor=lambda a: None)
    def forbidden(*args):
        raise AssertionError('source read after budget exhaustion')
    with pytest.raises(AccountingError, match='retention'):
        store.capture(SimpleNamespace(execute_command=forbidden), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=lambda a: None)
    assert len(list(tmp_path.iterdir())) == 1


def test_archive_byte_budget_does_not_publish_incomplete_anchor(tmp_path):
    store = archive.EvidenceArchive(tmp_path, max_total_bytes=1); anchors = []
    with pytest.raises(AccountingError, match='byte budget'):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=anchors.append)
    assert not anchors and not list(tmp_path.iterdir())


def test_unknown_retained_file_blocks_capture_without_cleanup(tmp_path):
    (tmp_path / 'unrecognized').write_bytes(b'preserve')
    store = archive.EvidenceArchive(tmp_path)
    with pytest.raises(AccountingError, match='unknown storage'):
        store.capture(SimpleNamespace(execute_command=lambda *a: source()), scope=lambda: 'a' * 40,
                      journal_head='b' * 64, persist_anchor=lambda a: None)
    assert (tmp_path / 'unrecognized').read_bytes() == b'preserve'
