"""Isolated observation attestation. Not installed in any production launcher.

Trusted controller code must supply independently captured native descriptors.
Keys travel only through a private bootstrap channel, never argv/env/heartbeats.
Controller restart loses trust: old records cannot restore registrations. These
observations grant no write, startup, shutdown or process-termination authority.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from scripts.genesis_background_ownership import SERVICES

FIELDS = ('pid', 'parent_pid', 'created', 'executable', 'command_sha256')


def encoded(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 16384:
        raise ValueError('Provenance frame outside bound')
    return raw


def descriptor(row):
    result = {name: row[name] for name in FIELDS}
    if (type(result['pid']) is not int or result['pid'] <= 0 or
            type(result['parent_pid']) is not int or result['parent_pid'] < 0 or
            not isinstance(result['executable'], str) or not result['executable'] or
            not isinstance(result['command_sha256'], str) or
            not re.fullmatch('[0-9a-f]{64}', result['command_sha256'])):
        raise ValueError('Native identity unavailable')
    created = datetime.fromisoformat(result['created'].replace('Z', '+00:00'))
    if created.tzinfo is None:
        raise ValueError('Native identity timezone missing')
    return result


def signed(key, body):
    return {'body': body, 'mac': hmac.new(key, encoded(body), hashlib.sha256).hexdigest()}


def authenticated(key, proof):
    if (not isinstance(proof, dict) or set(proof) != {'body', 'mac'} or
            not isinstance(proof['body'], dict) or not isinstance(proof['mac'], str) or
            not hmac.compare_digest(signed(key, proof['body'])['mac'], proof['mac'])):
        raise ValueError('Observation proof authentication failed')
    return proof['body']


def answer_launch(private_frame, actual_native, *, now=time.time_ns):
    """Fixture receiver: private frame is secret and must never be logged."""
    if not isinstance(private_frame, bytes) or not 0 < len(private_frame) <= 16384:
        raise ValueError('Private launch frame unavailable')
    frame = json.loads(private_frame)
    if set(frame) != {'challenge', 'key'} or not re.fullmatch('[0-9a-f]{64}', frame['key']):
        raise ValueError('Private launch key unavailable')
    body = frame['challenge']
    if (body['kind'] != 'genesis-launch-observation-v1' or
            body['owner'] != descriptor(actual_native) or
            type(body['expires_ns']) is not int or not 0 < body['expires_ns'] - now() <= 30_000_000_000):
        raise ValueError('Private launch target stale or replaced')
    return signed(bytes.fromhex(frame['key']), body)


class LaunchObservations:
    """Explicit trusted controller object. No env switch, CLI or persistence."""
    def __init__(self, native, *, now=time.time_ns):
        if not callable(native):
            raise ValueError('Independent native verifier required')
        self._native = native
        self._now = now
        self._session = secrets.token_hex(16)
        self._records = {}
        self._generations = {}
        self._lock = threading.RLock()

    def _current(self, owner):
        if descriptor(self._native(owner['pid'])) != owner:
            raise ValueError('Native process identity replaced or unavailable')

    def prepare(self, service, expected_owner):
        with self._lock:
            if service not in SERVICES or len(self._records) >= 7 and service not in self._records:
                raise ValueError('Service scope unavailable')
            if service in self._records and self._records[service]['phase'] != 'HOLD':
                raise ValueError('Duplicate launch claim; explicit retirement required')
            owner = descriptor(expected_owner)
            self._current(owner)
            if any(r['phase'] != 'HOLD' and r['challenge']['owner']['pid'] == owner['pid']
                   for r in self._records.values()):
                raise ValueError('Native process already claims a launch role')
            generation = self._generations.get(service, 0) + 1
            challenge = {'kind': 'genesis-launch-observation-v1', 'session': self._session,
                         'service': service, 'generation': generation, 'owner': owner,
                         'nonce': secrets.token_hex(32), 'expires_ns': self._now() + 30_000_000_000}
            key = secrets.token_bytes(32)
            self._records[service] = {'challenge': challenge, 'key': key, 'phase': 'PENDING'}
            self._generations[service] = generation
            return encoded({'challenge': challenge, 'key': key.hex()})

    def accept(self, service, proof):
        with self._lock:
            record = self._records.get(service)
            try:
                if record is None or record['phase'] != 'PENDING':
                    raise ValueError('Unknown, replayed or retired launch observation')
                body = authenticated(record['key'], proof)
                if encoded(body) != encoded(record['challenge']) or self._now() >= body['expires_ns']:
                    raise ValueError('Launch generation or deadline differs')
                self._current(body['owner'])
                if self._now() >= body['expires_ns']:
                    raise ValueError('Native verification exceeded observation deadline')
                record['phase'] = 'ATTESTED'
                return self.status(service)
            except Exception:
                if record is not None:
                    record['phase'] = 'HOLD'
                raise ValueError('Launch observation rejected; HOLD') from None

    def retire(self, service):
        with self._lock:
            if service in self._records:
                self._records[service]['phase'] = 'HOLD'

    def checked(self, service):
        """Trusted in-process access; never serialize the returned secret record."""
        with self._lock:
            record = self._records.get(service)
            if record is None or record['phase'] != 'ATTESTED':
                raise ValueError('Attested launch observation required')
            try:
                self._current(record['challenge']['owner'])
            except Exception:
                record['phase'] = 'HOLD'
                raise ValueError('Native observation stale; HOLD') from None
            return record

    def status(self, service):
        with self._lock:
            record = self._records.get(service)
            return {'service': service, 'phase': record['phase'] if record else 'UNREGISTERED',
                    'generation': self._generations.get(service),
                    'lifecycle_authorized': False, 'write_authorized': False,
                    'scope': 'ISOLATED_OBSERVATION_ONLY'}
