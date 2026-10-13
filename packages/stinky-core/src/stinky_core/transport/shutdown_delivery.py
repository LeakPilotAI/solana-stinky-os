"""Inactive authenticated request/processed-reply codec; no listener or activation.

Trusted bootstrap supplies a fresh private control key and independent native
controller verifier. Transport acceptance is never a shutdown acknowledgement.
"""
import asyncio
import hashlib
import hmac
import json
import math
import re
import time
import uuid

from stinky_core.transport.redis_accounting import AccountingError


def canonical(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 16384:
        raise AccountingError('Shutdown message exceeds bound')
    return raw


class ShutdownAuthority:
    def __init__(self, key, controller):
        if not isinstance(key, bytes) or len(key) != 32 or not re.fullmatch('[0-9a-f]{64}', controller):
            raise AccountingError('Fresh private control capability required')
        self._key = key
        self.controller = controller

    def seal(self, body):
        return {'body': body, 'mac': hmac.new(self._key, canonical(body), hashlib.sha256).hexdigest()}

    def open(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {'body', 'mac'}:
            raise AccountingError('Malformed shutdown envelope')
        expected = hmac.new(self._key, canonical(envelope['body']), hashlib.sha256).hexdigest()
        if not isinstance(envelope['mac'], str) or not hmac.compare_digest(envelope['mac'], expected):
            raise AccountingError('Unauthenticated shutdown message')
        return envelope['body']

    def request(self, target, generation, *, timeout=10):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise AccountingError('Bounded request deadline required')
        if not isinstance(target,str) or not re.fullmatch('[0-9a-f]{64}',target) or type(generation) is not int or generation <= 0:
            raise AccountingError('Exact target and lifecycle generation required')
        return self.seal({'kind': 'SHUTDOWN', 'controller': self.controller,
                          'target': target, 'generation': generation,
                          'request_id': uuid.uuid4().hex,
                          'expires_ns': time.time_ns() + int(timeout * 1e9)})

    def verify_reply(self, request, reply):
        original = self.open(request)
        body = self.open(reply)
        fields = {'kind', 'controller', 'target', 'generation', 'request_id', 'phase', 'ack', 'delivery_head'}
        if (not isinstance(body, dict) or set(body) != fields or body['kind'] != 'PROCESSED' or
            time.time_ns() >= original['expires_ns'] or
            any(body[k] != original[k] for k in ('controller', 'target', 'generation', 'request_id')) or
            body['phase'] != 'QUIESCED' or not isinstance(body['ack'],dict) or body['ack'].get('phase') != 'QUIESCED' or
            not re.fullmatch('[0-9a-f]{64}', body['delivery_head'])):
            raise AccountingError('No matching durable processed shutdown acknowledgment')
        return body['ack']


class ShutdownReceiver:
    def __init__(self, authority, *, manifest, generation, verify_controller, process, persist, hold):
        self.authority = authority
        self.manifest = manifest
        self.generation = generation
        self.verify_controller = verify_controller
        self.process = process
        self.persist = persist
        self.hold = hold
        self.used = False
        self.boot_id = uuid.uuid4().hex
        self.lock = asyncio.Lock()

    def target(self):
        # New receiver/bootstrap can never accept an old in-flight request even
        # if a caller mistakenly reuses its capability or lifecycle generation.
        return hashlib.sha256(canonical({'manifest':self.manifest(), 'boot_id':self.boot_id})).hexdigest()

    def record(self, body):
        head = self.persist(body)
        if not isinstance(head, str) or not re.fullmatch('[0-9a-f]{64}', head):
            raise AccountingError('Delivery audit not durable')
        return head

    async def receive(self, envelope):
        # Authentication precedes any mutation of participant or replay state.
        body = self.authority.open(envelope)
        fields = {'kind', 'controller', 'target', 'generation', 'request_id', 'expires_ns'}
        if (not isinstance(body, dict) or set(body) != fields or body['kind'] != 'SHUTDOWN' or
            body['controller'] != self.authority.controller or
            self.verify_controller() != self.authority.controller or
            body['target'] != self.target() or type(body['generation']) is not int or body['generation'] != self.generation() or
            not isinstance(body['request_id'], str) or not re.fullmatch('[0-9a-f]{32}', body['request_id']) or
            type(body['expires_ns']) is not int or not 0 < body['expires_ns'] - time.time_ns() <= 60_000_000_000):
            raise AccountingError('Stale, incorrectly targeted or unverified controller request')
        async with self.lock:
            if self.used:
                raise AccountingError('Shutdown delivery already consumed; fresh bootstrap required')
            self.used = True
            try:
                if self.verify_controller() != self.authority.controller or body['target'] != self.target():
                    raise AccountingError('Controller or receiver changed before dispatch')
                self.record({'stage': 'SHUTDOWN_DELIVERY_INTENT', **body})
                timeout = (body['expires_ns'] - time.time_ns()) / 1e9
                if timeout <= 0:
                    raise AccountingError('Shutdown deadline passed before processing')
                ack = await self.process({'request_id': body['request_id'], 'manifest_sha256': self.manifest()}, timeout)
                if (not isinstance(ack, dict) or ack.get('phase') != 'QUIESCED' or
                    ack.get('request_id') != body['request_id'] or
                    self.verify_controller() != self.authority.controller or
                    body['target'] != self.target() or body['generation'] != self.generation() or
                    time.time_ns() >= body['expires_ns']):
                    raise AccountingError('Processing evidence missing, late or replaced')
                head = self.record({'stage': 'SHUTDOWN_DELIVERY_PROCESSED', **body,
                                    'ack_sha256': hashlib.sha256(canonical(ack)).hexdigest()})
                if time.time_ns() >= body['expires_ns']:
                    raise AccountingError('Durable delivery completion exceeded deadline')
                return self.authority.seal({'kind': 'PROCESSED', 'controller': body['controller'],
                    'target': body['target'], 'generation': body['generation'],
                    'request_id': body['request_id'], 'phase': 'QUIESCED', 'ack': ack, 'delivery_head': head})
            except BaseException:
                self.hold()
                raise
