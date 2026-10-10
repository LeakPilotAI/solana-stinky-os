"""Inactive encrypted point-in-time archive. Never restores production Redis.

Archives retain actual DUMP bytes and complete stream metadata, not just hashes.
An independent trusted anchor is mandatory. A later archive cannot prove that
earlier expiry/eviction/trimmed data was preserved. Existing recovery gates stand.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

from scripts.redis_stream_integrity import READ, semantic_census, verify_semantic_recovery, framed_hash
from scripts.redis_snapshot_integrity import MAX_KEYS, MAX_KEY_BYTES
from scripts.redis_stream_integrity import MAX_ENTRIES, MAX_GROUPS, MAX_CONSUMERS
from scripts.redis_writer_broker import pack, unpack
from stinky_core.transport.redis_accounting import AccountingError

LIMIT = 128 * 1024 * 1024


class UserProtection:
    """Windows user-bound DPAPI; no plaintext payload or encryption key on disk."""
    def transform(self, value, *, decrypt=False):
        if os.name != 'nt':
            raise AccountingError('User-bound archive protection unavailable')
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

        def blob(data):
            backing = ctypes.create_string_buffer(data)
            return Blob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte))), backing

        source, source_memory = blob(value)
        entropy, entropy_memory = blob(b'genesis-redis-evidence-archive-v1')
        target = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if not function(ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                        1, ctypes.byref(target)):  # CRYPTPROTECT_UI_FORBIDDEN
            raise AccountingError('Archive protection failed')
        try:
            if target.size > LIMIT:
                raise AccountingError('Protected archive exceeds bound')
            return ctypes.string_at(target.data, target.size)
        finally:
            kernel.LocalFree(target.data)

    def seal(self, value):
        return self.transform(value)

    def open(self, value):
        return self.transform(value, decrypt=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def proof_for(raw):
    # Reuse the existing strict parser and completeness checks on actual bytes.
    if not isinstance(raw, (list, tuple)) or len(raw) != 2 or not isinstance(raw[1], list) or len(raw[1]) > MAX_KEYS:
        raise AccountingError('Archive dataset shape or key bound differs')
    if any(not isinstance(row, (list, tuple)) or len(row) != 5 or not isinstance(row[2], bytes) for row in raw[1]):
        raise AccountingError('Archive raw evidence incomplete')
    if sum(len(row[2]) for row in raw[1]) > MAX_KEY_BYTES:
        raise AccountingError('Archive dataset exceeds byte bound')
    client = SimpleNamespace(execute_command=lambda *args: raw)
    proof = semantic_census(client)
    verify_semantic_recovery(proof, proof, mode='rdb')
    return proof


class EvidenceArchive:
    def __init__(self, directory, *, protection=None, max_archives=128, max_total_bytes=1024 * 1024 * 1024):
        self.directory = Path(directory)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise AccountingError('Reviewed archive directory required')
        self.protection = protection or UserProtection()
        if type(max_archives) is not int or not 1 <= max_archives <= 128 or type(max_total_bytes) is not int or not 0 < max_total_bytes <= 1024 * 1024 * 1024:
            raise AccountingError('Archive retention budget outside bound')
        self.max_archives = max_archives
        self.max_total_bytes = max_total_bytes

    def require_epoch_budget(self, *, peak_appends_per_second, epoch_seconds,
                             measured_archive_bytes):
        """Necessary storage admission check, never a throughput certificate.

        The caller must supply independently measured demand and archive size.
        Each current trimming append consumes one complete archive. A quiet
        sample cannot establish zero demand. No artifact is removed or rotated.
        Call before credential issuance; passing this check grants no authority.
        """
        for value in (peak_appends_per_second, epoch_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise AccountingError('Measured demand and bounded epoch required')
        if epoch_seconds > 3600 or peak_appends_per_second > 1000000:
            raise AccountingError('Capacity measurement outside bound')
        if type(measured_archive_bytes) is not int or not 0 < measured_archive_bytes <= LIMIT:
            raise AccountingError('Measured protected archive size required')
        retained, count = self._retained_budget()
        required = math.ceil(peak_appends_per_second * epoch_seconds)
        available = min(self.max_archives - count,
                        (self.max_total_bytes - retained) // measured_archive_bytes)
        if required > available:
            raise AccountingError('Archive epoch capacity insufficient; activation blocked')
        return {'required_archives': required, 'available_archives': available,
                'required_bytes': required * measured_archive_bytes,
                'throughput_certified': False, 'writers_authorized': False}

    def retained_bytes(self):
        return self._retained_budget()[0]

    def _retained_budget(self):
        total = count = 0
        with os.scandir(self.directory) as rows:
            for row in rows:
                count += 1
                if count >= self.max_archives or row.is_symlink() or not row.is_file(follow_symlinks=False) or not re.fullmatch(r'[0-9a-f]{32}\.dpapi', row.name):
                    raise AccountingError('Archive retention exhausted or unknown storage; preserve all artifacts')
                size = row.stat(follow_symlinks=False).st_size
                if not 0 < size <= LIMIT:
                    raise AccountingError('Retained archive size outside bound')
                total += size
                if total >= self.max_total_bytes:
                    raise AccountingError('Archive byte budget exhausted; preserve all artifacts')
        return total, count

    def capture(self, client, *, scope, journal_head, persist_anchor):
        """Persist a full atomic Redis boundary, then anchor it independently.

        scope must reverify native endpoint/storage ownership and return its
        reviewed epoch. This does not fence writers or claim a migration boundary.
        Any anchor/fsync/readback failure leaves the new blob retained, unusable.
        """
        if not isinstance(journal_head, str) or not re.fullmatch('[0-9a-f]{64}', journal_head):
            raise AccountingError('Trusted receipt boundary required')
        retained = self.retained_bytes()
        epoch = scope()
        if not isinstance(epoch, str) or not re.fullmatch('[0-9a-f]{40}', epoch):
            raise AccountingError('Archive route epoch unavailable')
        raw = client.execute_command('EVAL_RO', READ, 0, MAX_KEYS, MAX_KEY_BYTES,
                                     MAX_ENTRIES, MAX_GROUPS, MAX_CONSUMERS)
        proof = proof_for(raw)
        if scope() != epoch:
            raise AccountingError('Archive source changed during capture')
        body = {'schema': 'genesis-redis-archive-v1', 'epoch': epoch,
                'journal_head': journal_head, 'raw': pack(raw)}
        plain = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        if len(plain) > LIMIT:
            raise AccountingError('Archive plaintext exceeds bound')
        sealed = self.protection.seal(plain)
        if not isinstance(sealed, bytes) or not 0 < len(sealed) <= LIMIT:
            raise AccountingError('Protected archive exceeds bound')
        if retained + len(sealed) > self.max_total_bytes:
            raise AccountingError('Archive byte budget exhausted; preserve all artifacts')
        name = os.urandom(16).hex() + '.dpapi'
        path = self.directory / name
        with path.open('xb') as stream:
            stream.write(sealed)
            stream.flush()
            os.fsync(stream.fileno())
        anchor = {'schema': body['schema'], 'file': name, 'bytes': len(sealed),
                  'ciphertext_sha256': digest(sealed), 'plaintext_sha256': digest(plain),
                  'epoch': epoch, 'journal_head': journal_head,
                  'observed_at_ms': proof['observed_at_ms']}
        self.read(anchor)  # readback/decrypt/strict parsing before external anchor
        persist_anchor(dict(anchor))  # must fsync outside this archive directory
        return anchor

    def read(self, anchor):
        required = {'schema', 'file', 'bytes', 'ciphertext_sha256', 'plaintext_sha256',
                    'epoch', 'journal_head', 'observed_at_ms'}
        if not isinstance(anchor, dict) or set(anchor) != required or anchor['schema'] != 'genesis-redis-archive-v1':
            raise AccountingError('Independent archive anchor unavailable')
        if not isinstance(anchor['file'], str) or not re.fullmatch(r'[0-9a-f]{32}\.dpapi', anchor['file']):
            raise AccountingError('Archive path outside reviewed boundary')
        if type(anchor['bytes']) is not int or not 0 < anchor['bytes'] <= LIMIT:
            raise AccountingError('Archive size outside bound')
        path = self.directory / anchor['file']
        if path.is_symlink():
            raise AccountingError('Archive link forbidden')
        with path.open('rb') as stream:
            sealed = stream.read(LIMIT + 1)
        if len(sealed) != anchor['bytes'] or digest(sealed) != anchor['ciphertext_sha256']:
            raise AccountingError('Archive ciphertext integrity differs')
        plain = self.protection.open(sealed)
        if len(plain) > LIMIT or digest(plain) != anchor['plaintext_sha256']:
            raise AccountingError('Archive plaintext integrity differs')
        try:
            body = json.loads(plain)
            if set(body) != {'schema', 'epoch', 'journal_head', 'raw'}:
                raise ValueError()
            if any(body[field] != anchor[field] for field in ('schema', 'epoch', 'journal_head')):
                raise ValueError()
            raw = unpack(body['raw'])
            proof = proof_for(raw)
            if proof['observed_at_ms'] != anchor['observed_at_ms']:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise AccountingError('Archive evidence malformed') from None
        return raw, proof

    def require_receipt(self, anchor, *, key_sha256, entry_id, payload_sha256, field_count):
        """Prove actual archived bytes; never exempts current recovery validation."""
        _, proof = self.read(anchor)
        matches = [entry for key in proof['keys'] if key['key_sha256'] == key_sha256
                   and key['type'] == 'stream' for entry in key['stable']['entries']
                   if entry['id'] == entry_id]
        if matches != [{'id': entry_id, 'payload_sha256': payload_sha256, 'field_count': field_count}]:
            raise AccountingError('Required historical payload not archived')
        return True


class ArchivedRetention:
    """Inactive single-flight custody using existing complete encrypted archives.

    Noeviction remains mandatory: Redis can evict on paths outside this controller.
    Already-expiring values require a prior durable archive, not a late snapshot.
    This supports stream trimming only; SET/EX remains rejected until value custody
    can precede expiry installation. It never claims complete production coverage.
    """
    def __init__(self, store, client, ledger, *, scope, configuration, expiring_keys):
        from scripts.redis_writer_broker import RetentionBoundary
        RetentionBoundary(configuration, expiring_keys)
        self.store = store; self.client = client; self.ledger = ledger
        self.scope = scope; self.anchors = []; self.held = False

    def before(self, name, args):
        from scripts.redis_production_adapters import validate_command
        validate_command(name, args)
        if self.held:
            raise AccountingError('Archive custody held')
        if name == 'SET':
            raise AccountingError('Expiry installation requires pre-dispatch value custody')
        try:
            self.ledger.settled()  # No competing or uncertain physical operation.
            if name == 'XADD' and args[1].upper() in (b'MAXLEN', b'MINID'):
                # Actual production MAXLEN20000 is supported; zero-length writes
                # could remove the newly returned ID before any post-write census.
                i = 2 + (args[2] in (b'~', b'='))
                if args[1].upper() != b'MAXLEN' or not args[i].isdigit() or int(args[i]) < 1:
                    raise AccountingError('Retention form not certified')
                if len(self.anchors) >= 128:
                    raise AccountingError('Archive custody epoch capacity exhausted')
                anchor = self.store.capture(self.client, scope=self.scope,
                    journal_head=self.ledger.journal.previous,
                    persist_anchor=lambda a: self.ledger.journal.persist(
                        {'stage': 'RETENTION_CUSTODY', 'next_token': len(self.ledger.commands)+1,
                         'args_sha256': framed_hash(args),
                         'anchor': a}))
                # The independent durable receipt exists before begin_command can
                # issue its intent and before Redis receives a trimming command.
                self.anchors.append(anchor)
                point = self.store.read(anchor)[1]
                if any(key['expires_at_ms'] != -1 for key in point['keys']):
                    raise AccountingError('Unaccounted automatic expiry at custody boundary')
                self.verify(self.ledger, point)
        except BaseException:
            self.held = True
            raise

    def verify(self, ledger, proof):
        """Current-state validation plus actual-byte historical receipt coverage.

        This never normalizes current consumer metadata or proves target recovery.
        The coordinator must still compare complete current source/target proofs.
        """
        try:
            ledger.settled()
            verify_semantic_recovery(proof, proof, mode='rdb')
            history = [proof] + [self.store.read(anchor)[1] for anchor in self.anchors]
            for row in ledger.commands.values():
                if row.get('command') != 'XADD':
                    continue
                matches = [entry for point in history for key in point['keys']
                           if key['type'] == 'stream' and key['key_sha256'] == row['key_sha256']
                           for entry in key['stable']['entries'] if entry['id'] == row['entry_id']]
                if not matches or any(entry['payload_sha256'] != row['payload_sha256'] or
                                      entry['field_count'] != row['field_count'] for entry in matches):
                    raise AccountingError('Acknowledged historical payload absent or contradictory')
            return {'acknowledged': len(ledger.commands), 'unresolved': 0,
                    'verified_archive_boundaries': len(self.anchors)}
        except BaseException:
            self.held = True
            raise
