"""Inactive compact append custody. No production controls or automatic replay.

Payload bytes are durable before dispatch; the exact Redis entry is independently
observed before its receipt settles. Full current-state recovery remains separate.
Segments hand off only after fsync/readback and an independently anchored seal.
"""
from __future__ import annotations

import json
import os
import re
import struct
import stat
import threading
from pathlib import Path

from scripts.redis_evidence_archive import UserProtection, digest
from scripts.redis_writer_broker import pack, unpack
from scripts.redis_stream_integrity import framed_hash, verify_semantic_recovery
from stinky_core.transport.redis_accounting import AccountingError

OBSERVE = "return redis.call('XRANGE', KEYS[1], ARGV[1], ARGV[1], 'COUNT', 1)"
SEGMENT_BYTES = 8 * 1024 * 1024


class FixedReadonlyEntryProbe:
    """Three fixed read-only observations, one transport write; no mutation API.

    The trusted controller supplies the already scoped read-only observer client.
    Both remote epochs are returned and checked, never inferred from cached state.
    Payloads are still compared byte-for-byte with freshly decrypted custody.
    """
    def __init__(self,client):self.client=client
    def __call__(self,key,entry_id):
        if (not isinstance(key,bytes) or not isinstance(entry_id,str) or
            not re.fullmatch('[0-9]+-[0-9]+',entry_id)):
            raise AccountingError('Entry observation identity unavailable')
        # Redis INFO/XRANGE have no mutation or transaction/consumer-state effects.
        # A read-only retry still has to satisfy both independently returned epochs.
        with self.client.pipeline(transaction=False) as probe:
            probe.info('server')
            probe.execute_command('EVAL_RO',OBSERVE,1,key,entry_id)
            probe.info('server')
            rows=probe.execute()
        if not isinstance(rows,list) or len(rows)!=3:
            raise AccountingError('Entry observation response incomplete')
        def epoch(info):
            if not isinstance(info,dict):raise AccountingError('Observer epoch unavailable')
            value=info.get('run_id',info.get(b'run_id'))
            if isinstance(value,bytes):value=value.decode('ascii')
            if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{40}',value):
                raise AccountingError('Observer epoch malformed')
            return value
        return epoch(rows[0]),rows[1],epoch(rows[2])


class AppendStore:
    def __init__(self, directory, *, writable=True, protection=None,
                 segment_bytes=SEGMENT_BYTES, max_segments=128,
                 max_total_bytes=1024 * 1024 * 1024):
        self.directory = Path(directory)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise AccountingError('Reviewed custody directory required')
        if (type(segment_bytes) is not int or not 1024 <= segment_bytes <= SEGMENT_BYTES or
            type(max_segments) is not int or not 1 <= max_segments <= 128 or
            type(max_total_bytes) is not int or not 0 < max_total_bytes <= 1024 * 1024 * 1024):
            raise AccountingError('Custody storage bound unavailable')
        self.protection = protection or UserProtection()
        self.segment_bytes = segment_bytes; self.max_segments = max_segments
        self.max_total_bytes = max_total_bytes; self.writable = writable
        self.records = {}; self.seals = []; self.held = False
        self.stream = None; self.name = None; self.size = 0; self.total = 0
        self.reader = None; self.reader_name = None
        self.lock = threading.RLock()
        count = 0
        with os.scandir(self.directory) as rows:
            for entry in rows:
                count += 1
                if (count > max_segments or entry.is_symlink() or
                    not entry.is_file(follow_symlinks=False) or
                    not re.fullmatch('[0-9a-f]{32}\\.custody', entry.name) or
                    not 0 < entry.stat(follow_symlinks=False).st_size <= segment_bytes):
                    raise AccountingError('Unverified custody storage; preserve artifacts')
                self.total += entry.stat(follow_symlinks=False).st_size
                if self.total > max_total_bytes:
                    raise AccountingError('Custody storage exhausted')
        if writable and count:
            raise AccountingError('Existing custody requires held recovery, never append/replay')
        self.count = count

    def read(self, anchor):
        fields = {'schema', 'file', 'offset', 'bytes', 'token', 'epoch',
                  'args_sha256', 'ciphertext_sha256', 'plaintext_sha256'}
        if (not isinstance(anchor, dict) or set(anchor) != fields or
            anchor['schema'] != 'genesis-append-custody-v1' or
            not isinstance(anchor['file'], str) or
            not re.fullmatch('[0-9a-f]{32}\\.custody', anchor['file']) or
            type(anchor['offset']) is not int or anchor['offset'] < 0 or
            type(anchor['bytes']) is not int or not 0 < anchor['bytes'] <= self.segment_bytes - 4 or
            anchor['offset'] + anchor['bytes'] + 4 > self.segment_bytes or
            type(anchor['token']) is not int or not 0 < anchor['token'] <= 50000 or
            not isinstance(anchor['epoch'], str) or not re.fullmatch('[0-9a-f]{40}', anchor['epoch'])):
            raise AccountingError('Independent custody anchor unavailable')
        path = self.directory / anchor['file']
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > self.segment_bytes:
            raise AccountingError('Custody file ownership/bound differs')
        with self.lock:
            if self.stream is not None and self.name == anchor['file']:
                stream = self.stream
            else:
                if self.reader_name != anchor['file']:
                    if self.reader is not None:self.reader.close()
                    self.reader = path.open('rb', buffering=0)
                    self.reader_name = anchor['file']
                stream = self.reader
            native = os.fstat(stream.fileno())
            if (native.st_ino,native.st_dev)!=(info.st_ino,info.st_dev):
                raise AccountingError('Custody native file identity changed')
            position = stream.tell()
            try:
                stream.seek(anchor['offset'])
                header = stream.read(4)
                if len(header) != 4 or struct.unpack('>I', header)[0] != anchor['bytes']:
                    raise AccountingError('Custody record truncated or altered')
                sealed = stream.read(anchor['bytes'])
            finally:stream.seek(position)
        if len(sealed) != anchor['bytes'] or digest(sealed) != anchor['ciphertext_sha256']:
            raise AccountingError('Custody ciphertext differs')
        plain = self.protection.open(sealed)
        if len(plain) > self.segment_bytes or digest(plain) != anchor['plaintext_sha256']:
            raise AccountingError('Custody plaintext differs')
        try:
            body = json.loads(plain)
            if set(body) != {'schema', 'token', 'epoch', 'args'}:
                raise ValueError()
            if any(body[k] != anchor[k] for k in ('schema', 'token', 'epoch')):
                raise ValueError()
            args = unpack(body['args'])
            from scripts.redis_production_adapters import validate_command
            validate_command('XADD', args)
            if framed_hash(args) != anchor['args_sha256']:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise AccountingError('Custody payload evidence malformed') from None
        return args

    def seal(self, journal):
        if self.stream is None:
            return
        self.stream.flush(); os.fsync(self.stream.fileno())
        self.stream.close(); self.stream = None
        with (self.directory / self.name).open('rb') as source:
            raw = source.read(self.segment_bytes + 1)
        if len(raw) != self.size or len(raw) > self.segment_bytes:
            self.held = True
            raise AccountingError('Custody handoff size differs')
        seal = {'file': self.name, 'bytes': self.size, 'sha256': digest(raw)}
        try:
            journal.persist({'stage': 'CUSTODY_SEGMENT_SEALED', **seal})
        except BaseException:
            self.held = True
            raise
        self.seals.append(seal)

    def verify_inventory(self, anchors, seals):
        """Read-only recovery; reject unanchored tails instead of discarding them."""
        if len(anchors) > 50000 or len(seals) > self.max_segments:
            raise AccountingError('Custody recovery inventory exceeds bound')
        files = {}
        tokens = set()
        for anchor in anchors:
            if anchor['token'] in tokens:
                raise AccountingError('Duplicate recovered custody token')
            tokens.add(anchor['token'])
            self.read(anchor)
            files.setdefault(anchor['file'], []).append(anchor)
        with os.scandir(self.directory) as rows:
            found = set()
            for row in rows:
                if len(found) >= self.max_segments or row.name not in files or row.is_symlink():
                    raise AccountingError('Unregistered custody storage; preserve it')
                found.add(row.name)
        if found != set(files):
            raise AccountingError('Required custody segment missing')
        for name, records in files.items():
            end = 0
            for anchor in sorted(records, key=lambda a:a['offset']):
                if anchor['offset'] != end:
                    raise AccountingError('Custody record omitted/reordered')
                end += anchor['bytes'] + 4
            if (self.directory/name).stat().st_size != end:
                raise AccountingError('Unaccounted custody tail; preserve it')
        sealed = set()
        for seal in seals:
            if (set(seal) != {'file','bytes','sha256'} or seal['file'] not in files or
                seal['file'] in sealed or type(seal['bytes']) is not int or
                not 0 < seal['bytes'] <= self.segment_bytes):
                raise AccountingError('Independent handoff seal unavailable')
            with (self.directory/seal['file']).open('rb') as source:
                raw = source.read(self.segment_bytes+1)
            if len(raw) != seal['bytes'] or digest(raw) != seal['sha256']:
                raise AccountingError('Custody handoff seal differs')
            sealed.add(seal['file'])
        return True

    def prepare(self, token, args, *, epoch, journal, persist=None):
        with self.lock:
            if self.held or not self.writable:
                raise AccountingError('Custody held/read-only')
            if type(token) is not int or not 0 < token <= 50000:
                raise AccountingError('Custody token bound unavailable')
            if not isinstance(epoch, str) or not re.fullmatch('[0-9a-f]{40}', epoch):
                raise AccountingError('Custody source epoch unavailable')
            from scripts.redis_production_adapters import validate_command
            validate_command('XADD', args)
            if len(args) > 1024 or sum(map(len, args)) > 4 * 1024 * 1024:
                raise AccountingError('Custody argument bound exceeded')
            if token in self.records:
                if persist is not None:
                    raise AccountingError('Existing custody cannot issue a new atomic intent')
                anchor = self.records[token]
                if self.read(anchor) != args or anchor['epoch'] != epoch:
                    self.held = True
                    raise AccountingError('Duplicate custody token contradicts prior payload')
                return dict(anchor)  # Never retry the physical Redis mutation here.
            try:
                body = {'schema': 'genesis-append-custody-v1', 'token': token,
                        'epoch': epoch, 'args': pack(args)}
                plain = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
                if len(plain) > self.segment_bytes - 4:
                    raise AccountingError('Custody record exceeds segment bound')
                sealed = self.protection.seal(plain)
                if not isinstance(sealed, bytes) or not 0 < len(sealed) <= self.segment_bytes - 4:
                    raise AccountingError('Protected custody exceeds segment bound')
                size = len(sealed) + 4
                if self.total + size > self.max_total_bytes:
                    raise AccountingError('Custody storage exhausted; no dispatch')
                if self.stream is not None and self.size + size > self.segment_bytes:
                    self.seal(journal)
                if self.stream is None:
                    if self.count >= self.max_segments:
                        raise AccountingError('Custody segments exhausted; no dispatch')
                    self.name = os.urandom(16).hex() + '.custody'
                    self.stream = (self.directory / self.name).open('x+b', buffering=0)
                    self.count += 1; self.size = 0
                offset = self.size
                frame = struct.pack('>I', len(sealed)) + sealed
                if self.stream.write(frame) != len(frame):
                    raise AccountingError('Partial custody frame; no dispatch')
                self.stream.flush(); os.fsync(self.stream.fileno())
                self.size += size; self.total += size
                anchor = {'schema': body['schema'], 'file': self.name, 'offset': offset,
                          'bytes': len(sealed), 'token': token, 'epoch': epoch,
                          'args_sha256': framed_hash(args), 'ciphertext_sha256': digest(sealed),
                          'plaintext_sha256': digest(plain)}
                if self.read(anchor) != args:
                    raise AccountingError('Custody readback differs')
                mark={'stage': 'APPEND_CUSTODY', 'anchor': anchor}
                if persist is None:journal.persist(mark)
                else:persist(mark)
                self.records[token] = anchor
                return dict(anchor)
            except BaseException:
                self.held = True
                raise

    def close(self):
        if self.stream is not None:
            self.stream.close(); self.stream = None
        if self.reader is not None:
            self.reader.close(); self.reader = None; self.reader_name = None


class AppendCustody:
    single_flight_backpressure = True
    atomic_receipt = True
    atomic_intent = True
    def __init__(self, store, base_archive, client, ledger, *, scope,
                 configuration, expiring_keys, entry_probe=None):
        from scripts.redis_writer_broker import RetentionBoundary
        RetentionBoundary(configuration, expiring_keys)
        self.store = store; self.base_archive = base_archive
        self.client = client; self.ledger = ledger; self.scope = scope
        if entry_probe is not None and not isinstance(entry_probe,FixedReadonlyEntryProbe):
            raise AccountingError('Fixed read-only observation probe required')
        self.entry_probe=entry_probe
        self.base_anchor = None; self.observed = {}; self.held = False

    def initialize(self):
        """Controller-only before writer authority; never race blocked consumers."""
        if self.base_anchor is not None:
            return
        self.ledger.settled()
        self.base_anchor = self.base_archive.capture(self.client, scope=self.scope,
            journal_head=self.ledger.journal.previous,
            persist_anchor=lambda anchor:self.ledger.journal.persist({
                'stage':'BASE_CUSTODY','anchor':anchor}))
        base=self.base_archive.read(self.base_anchor)[1]
        if any(k['expires_at_ms']!=-1 for k in base['keys']):
            self.held=True
            raise AccountingError('Unaccounted expiry at initial custody boundary')
        self.verify(self.ledger,base)

    @staticmethod
    def conflicts(row, name):
        # Group delivery can block for the real production5000ms. Serializing
        # that pending read ahead of XADD would prevent the producer unblocking it.
        return name=='XADD' and row.get('command')=='XADD'

    @staticmethod
    def admission_notification_required(name):
        # Only append settlement releases the append/append conflict. Group
        # acknowledgements cannot release it and must not wake every producer.
        return name=='XADD'

    def before(self, name, args, *, intent=None):
        from scripts.redis_production_adapters import validate_command
        validate_command(name, args)
        if self.held:
            raise AccountingError('Append custody held')
        if name == 'SET':
            raise AccountingError('Expiry requires separately certified custody')
        try:
            if name != 'XADD':
                return
            if args[1].upper() in (b'MAXLEN', b'MINID'):
                i = 2 + (args[2] in (b'~', b'='))
                if args[1].upper() != b'MAXLEN' or not args[i].isdigit() or int(args[i]) < 1:
                    raise AccountingError('Unsupported retention cannot preserve new entry')
            if self.base_anchor is None:
                self.initialize()
            persist=None
            if intent is not None:
                token=len(self.ledger.commands)+1
                if (intent.get('token')!=token or intent.get('command')!='XADD' or
                    intent.get('state')!='ISSUED' or intent.get('args_sha256')!=framed_hash(args)):
                    raise AccountingError('Custody intent identity differs')
                persist=lambda mark:self.ledger.journal.persist_many([
                    mark,{'stage':'COMMAND_INTENT',**intent}])
            self.store.prepare(len(self.ledger.commands)+1, args, epoch=self.scope(),
                               journal=self.ledger.journal,persist=persist)
        except BaseException:
            self.held = True
            raise

    def observe(self, row, *, persist=None):
        if row['command'] != 'XADD':
            return
        try:
            token = row['token']; anchor = self.store.records[token]
            args = self.store.read(anchor)
            from scripts.redis_production_adapters import append_fields
            expected = append_fields(args)
            if self.entry_probe is None:
                epoch=self.scope()
                if epoch!=anchor['epoch']:raise AccountingError('Custody source changed before observation')
                raw=self.client.execute_command('EVAL_RO',OBSERVE,1,args[0],row['entry_id'])
                after=self.scope()
            else:epoch,raw,after=self.entry_probe(args[0],row['entry_id'])
            if epoch != anchor['epoch']:
                raise AccountingError('Custody source changed before observation')
            if (raw != [[row['entry_id'].encode('ascii'), expected]] or after != epoch):
                raise AccountingError('Actual Redis entry absent or contradicts prepared bytes')
            mark = {'token': token, 'entry_id': row['entry_id'],
                    'anchor': dict(anchor), 'payload_sha256': framed_hash(expected),
                    'field_count': len(expected)//2}
            if persist is None:self.ledger.journal.persist({'stage': 'CUSTODY_OBSERVED', **mark})
            else:persist(mark)
            getattr(self.ledger.journal,'after_commit',lambda action:action())(
                lambda:self.observed.__setitem__(token,mark))
        except BaseException:
            self.held = True
            raise

    def verify(self, ledger, proof):
        try:
            ledger.settled(); verify_semantic_recovery(proof, proof, mode='rdb')
            points = [proof]
            if self.base_anchor is not None:
                points.append(self.base_archive.read(self.base_anchor)[1])
            entries = {}
            for point in points:
                for key in point['keys']:
                    if key['type'] != 'stream':
                        continue
                    for entry in key['stable']['entries']:
                        address = (key['key_sha256'], entry['id'])
                        if address in entries and entries[address] != entry:
                            raise AccountingError('Current/base payload contradiction')
                        entries[address] = entry
            for token, row in ledger.commands.items():
                if row.get('command') != 'XADD':
                    continue
                found = entries.get((row['key_sha256'], row['entry_id']))
                if found is not None and (found['payload_sha256'] != row['payload_sha256'] or
                                           found['field_count'] != row['field_count']):
                    raise AccountingError('Current/base payload contradicts receipt')
                mark = self.observed.get(token)
                if mark is not None:
                    args = self.store.read(mark['anchor'])
                    from scripts.redis_production_adapters import append_fields
                    fields = append_fields(args)
                    if (mark['entry_id'] != row['entry_id'] or digest(args[0]) != row['key_sha256'] or
                        framed_hash(fields) != row['payload_sha256'] or len(fields)//2 != row['field_count'] or
                        mark['payload_sha256'] != row['payload_sha256'] or mark['field_count'] != row['field_count']):
                        raise AccountingError('Observed custody contradicts receipt')
                elif found is None:
                    raise AccountingError('Acknowledged payload has no observed custody')
            return {'acknowledged': len(ledger.commands), 'unresolved': 0,
                    'observed_append_records': len(self.observed)}
        except BaseException:
            self.held = True
            raise
