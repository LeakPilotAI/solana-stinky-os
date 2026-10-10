"""Inactive broker restart recovery. Every recovered route remains HOLD.

This is a revocation/reconstruction boundary, not an automatic resume or replay.
The trusted journal head must survive independently; missing evidence fails closed.
"""
from __future__ import annotations

import re
from scripts.redis_production_adapters import read_records, ProductionAcknowledgements
from stinky_core.transport.redis_accounting import AccountingError, identity, MUTATIONS
from types import MappingProxyType


class HeldRecoveryLedger(ProductionAcknowledgements):
    """Inspection-only reconstruction: no generation can dispatch through it."""
    def forbidden(self, *args, **kwargs):
        raise AccountingError('Recovered broker remains held; explicit route certification required')

    register_connection = forbidden
    retire_connection = forbidden
    begin_command = forbidden
    complete_command = forbidden
    reject_group_exists = forbidden
    begin = forbidden
    begin_metadata = forbidden
    acknowledged = forbidden
    acknowledged_metadata = forbidden


def require(condition):
    if not condition:
        raise AccountingError('Broker recovery evidence incomplete or contradictory')


def fingerprint(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value))


def recover_held_boundary(path, *, expected_head, next_journal, revoke, verify_revoked):
    """Rebuild settled/unknown intents and revoke old principals before returning.

    revoke and verify_revoked must use an independently pinned credential authority.
    They receive exact known principals only. A failed action never returns a route.
    Unrecorded principals still require the existing complete ACL inventory gate.
    New native manifests/connections/credentials cannot inherit the old generation.
    """
    rows = read_records(path, expected_head=expected_head)
    require(bool(rows) and rows[0].get('stage') == 'BROKER_ROUTE')
    route = rows[0]
    require(set(route) == {'stage', 'server_epoch', 'endpoint', 'generation', 'manifest'})
    require(isinstance(route['server_epoch'], str) and re.fullmatch('[0-9a-f]{40}', route['server_epoch']))
    require(isinstance(route['endpoint'], str) and re.fullmatch('[A-Za-z0-9_-]{1,80}', route['endpoint']))
    require(type(route['generation']) is int and route['generation'] > 0)
    require(isinstance(route['manifest'], list) and 0 < len(route['manifest']) <= 128)
    owners = {o['pid']: identity(o) for o in route['manifest']}
    require(len(owners) == len(route['manifest']))
    bindings = {}; commands = {}; principals = {}; writers = set()
    for record in rows[1:]:
        require(isinstance(record, dict))
        if 'generation' in record:
            require(type(record['generation']) is int and record['generation'] == route['generation'])
        stage = record.get('stage')
        if stage == 'CONNECTION_REGISTERED':
            require(set(record) == {'stage', 'writer', 'owner', 'client_id', 'server_epoch', 'generation', 'active'})
            owner = identity(record['owner'])
            require(owners.get(owner['pid']) == owner)
            writer = record['writer']
            require(isinstance(writer, str) and writer.startswith(f"{owner['pid']}-{owner['creation_ticks']}-"))
            require(type(record['client_id']) is int and record['client_id'] > 0 and record['active'] is True)
            require(record['server_epoch'] == route['server_epoch'] and record['generation'] == route['generation'])
            key = (writer, record['client_id'], record['generation'])
            require(key not in bindings and not any(b['active'] and b['client_id'] == record['client_id'] for b in bindings.values()))
            bindings[key] = {k: v for k, v in record.items() if k != 'stage'}; writers.add(writer)
        elif stage == 'CONNECTION_RETIRED':
            require(set(record) == {'stage', 'writer', 'client_id', 'generation'})
            key = (record['writer'], record['client_id'], record['generation'])
            require(key in bindings and bindings[key]['active'])
            bindings[key]['active'] = False
        elif stage == 'COMMAND_INTENT':
            token = record.get('token')
            require(type(token) is int and token == len(commands) + 1 and token <= 50000)
            require(record.get('state') == 'ISSUED' and record.get('command') in MUTATIONS and record['command'] != 'BRPOP')
            require(record.get('classification') == MUTATIONS[record['command']])
            fingerprint(record.get('args_sha256'))
            key = (record.get('writer'), record.get('connection_id'), record.get('generation'))
            require(key in bindings and bindings[key]['active'])
            required = {'stage', 'token', 'writer', 'command', 'classification', 'args_sha256', 'connection_id', 'generation', 'state'}
            if record['command'] == 'XADD':
                required |= {'key_sha256', 'payload_sha256', 'field_count'}
                fingerprint(record.get('key_sha256')); fingerprint(record.get('payload_sha256'))
                require(type(record.get('field_count')) is int and record['field_count'] > 0)
            else:
                required |= {'operation'}; require(record.get('operation') == record['command'])
            require(set(record) == required)
            commands[token] = {k: v for k, v in record.items() if k != 'stage'}
        elif stage == 'COMMAND_REPLY':
            token = record.get('token'); original = commands.get(token)
            require(original is not None and original['state'] == 'ISSUED')
            require(record.get('state') == 'ACKNOWLEDGED' and record.get('endpoint_id') == route['endpoint'])
            fingerprint(record.get('reply_sha256'))
            require(all(record.get(k) == v for k, v in original.items() if k != 'state'))
            extra = {'stage', 'endpoint_id', 'reply_sha256'}
            if original['command'] == 'XADD':
                extra.add('entry_id')
                require(isinstance(record.get('entry_id'), str) and re.fullmatch('[0-9]+-[0-9]+', record['entry_id']))
            if record.get('outcome') is not None:
                extra |= {'outcome', 'error_code'}
                require(original['command'] == 'XGROUP CREATE' and record['outcome'] == 'REJECTED_NO_EFFECT' and record.get('error_code') == 'BUSYGROUP')
            require(set(record) == set(original) | extra)
            commands[token] = {k: v for k, v in record.items() if k != 'stage'}
        elif stage == 'CONNECTION_CREDENTIAL_ISSUED':
            require(set(record) == {'stage', 'principal', 'owner', 'role', 'generation', 'server_epoch'})
            principal = record['principal']; owner = identity(record['owner'])
            require(isinstance(principal, str) and re.fullmatch('genesis-c66-[0-9a-f]{32}', principal) and principal not in principals)
            require(owners.get(owner['pid']) == owner and record['generation'] == route['generation'] and record['server_epoch'] == route['server_epoch'])
            principals[principal] = dict(record)
        elif stage == 'CONNECTION_CREDENTIAL_SEALED':
            require(set(record) == {'stage', 'principal', 'client_id', 'generation', 'server_epoch'})
            require(record['principal'] in principals and 'client_id' not in principals[record['principal']])
            require(type(record['client_id']) is int and record['client_id'] > 0 and record['generation'] == route['generation'] and record['server_epoch'] == route['server_epoch'])
            principals[record['principal']]['client_id'] = record['client_id']
        elif stage == 'SERVER_WRITER_FENCE':
            require(set(record) == {'stage', 'fenced', 'server_epoch'} and type(record['fenced']) is bool and record['server_epoch'] == route['server_epoch'])
        elif stage == 'BROKER_CREDENTIALS_REVOKED':
            require(set(record) == {'stage'})
        else:
            raise AccountingError('Unknown broker recovery stage; route held')
    require(bool(writers))
    # No stale binding survives restart, even if Redis retained its native CID.
    for principal in sorted(principals):
        revoke(principal)
        require(verify_revoked(principal) is True)
    for binding in bindings.values():
        binding['active'] = False
    ledger = HeldRecoveryLedger(next_journal, sorted(writers))
    ledger.commands = MappingProxyType({k: MappingProxyType(v) for k, v in commands.items()})
    ledger.bindings = MappingProxyType({k: MappingProxyType(v) for k, v in bindings.items()})
    next_journal.persist({'stage': 'RECOVERED_HELD_BOUNDARY', 'source_head': expected_head,
                          'next_generation': route['generation'] + 1,
                          'unresolved': sum(r['state'] != 'ACKNOWLEDGED' for r in commands.values()),
                          'revoked_principals': len(principals)})
    return {'ledger': ledger, 'route': dict(route), 'held': True, 'fenced': True,
            'next_generation': route['generation'] + 1}
