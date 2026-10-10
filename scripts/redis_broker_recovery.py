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


def recover_held_boundary(path, *, expected_head, next_journal, revoke, verify_revoked, verify_archive=None, parent_loader=None):
    """Rebuild settled/unknown intents and revoke old principals before returning.

    revoke and verify_revoked must use an independently pinned credential authority.
    They receive exact known principals only. A failed action never returns a route.
    Unrecorded principals still require the existing complete ACL inventory gate.
    New native manifests/connections/credentials cannot inherit the old generation.
    """
    rows = read_records(path, expected_head=expected_head)
    require(bool(rows) and rows[0].get('stage') == 'BROKER_ROUTE')
    route = rows[0]
    require(set(route)-{'parent_head','writers'} == {'stage','server_epoch','endpoint','generation','manifest'})
    require(isinstance(route['server_epoch'], str) and re.fullmatch('[0-9a-f]{40}', route['server_epoch']))
    require(isinstance(route['endpoint'], str) and re.fullmatch('[A-Za-z0-9_-]{1,80}', route['endpoint']))
    require(type(route['generation']) is int and route['generation'] > 0)
    require(isinstance(route['manifest'], list) and 0 < len(route['manifest']) <= 128)
    owners = {o['pid']: identity(o) for o in route['manifest']}
    require(len(owners) == len(route['manifest']))
    bindings = {}; commands = {}; principals = {}; writers = set(); archives = []; custody = {}
    if 'writers' in route:
        require(isinstance(route['writers'],list) and 0<len(route['writers'])<=1024 and len(set(route['writers']))==len(route['writers']))
        require(all(isinstance(w,str) and any(w.startswith(f"{o['pid']}-{o['creation_ticks']}-") for o in owners.values()) for w in route['writers']))
        writers=set(route['writers'])
    if 'parent_head' in route:
        fingerprint(route['parent_head']); require(callable(parent_loader))
        parent = parent_loader(route['parent_head'])
        require(parent.get('source_head') == route['parent_head'] and parent.get('held') is True
                and isinstance(parent.get('ledger'), HeldRecoveryLedger))
        require(parent['next_generation'] == route['generation'])
        parent['ledger'].settled()
        commands = {token: dict(row) for token,row in parent['ledger'].commands.items()}
        archives = list(parent.get('archive_anchors', ()))
        for anchor in archives:
            require(callable(verify_archive) and verify_archive(anchor) is True)
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
            if 'writers' in route:require(writer in writers)
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
            if token in custody:require(record['command']=='XADD' and record['args_sha256']==custody[token])
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
        elif stage == 'RETENTION_CUSTODY':
            require(set(record)=={'stage','next_token','args_sha256','anchor'})
            token=record['next_token']; require(type(token) is int and token==len(commands)+1 and token not in custody)
            fingerprint(record['args_sha256'])
            require(callable(verify_archive) and verify_archive(record['anchor']) is True)
            custody[token]=record['args_sha256'];archives.append(record['anchor'])
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
            'next_generation': route['generation'] + 1, 'source_head': expected_head,
            'archive_anchors': tuple(archives)}


def reauthorize_held_route(recovered, *, journal, credentials, manifest, verify_native,
                           retention, server_epoch, endpoint, authorize, grant_path, writer_roles=None):
    """Trusted-controller-only fresh authorization. No production bootstrap/CLI.

    An exclusive fsynced grant consumes this source boundary once. Old receipts
    remain in the ledger and parent anchor chain; unknown replies prohibit resume.
    The caller must independently pin scope and preserve every parent journal/head.
    """
    import json, hashlib, os
    from pathlib import Path
    from scripts.redis_writer_broker import WriterBroker
    require(recovered.get('held') is True and isinstance(recovered.get('ledger'),HeldRecoveryLedger))
    recovered['ledger'].settled()
    fingerprint(recovered.get('source_head'))
    fresh={pid:identity(verify_native(pid)) for pid in manifest}
    require(fresh==manifest and bool(fresh) and len(fresh)<=128 and all(pid==owner['pid'] for pid,owner in fresh.items()))
    credentials.check_scope();require(credentials.verify_principals() is True)
    require(not credentials.tickets)  # No inherited or sealed old connection.
    request={'source_head':recovered['source_head'],'generation':recovered['next_generation'],
             'server_epoch':server_epoch,'endpoint':endpoint,
             'manifest_sha256':hashlib.sha256(json.dumps(fresh,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    require(authorize(dict(request)) is True)
    # Preserve all old ACKs. Only current native writer IDs may issue new intents.
    owners=tuple(fresh.values())
    if writer_roles is None:
        writers={w for w in recovered['ledger'].writers if any(w.startswith(f"{o['pid']}-{o['creation_ticks']}-") for o in owners)}
    else:
        require(set(writer_roles)==set(fresh))
        oldroles={}
        for old in recovered['route']['manifest']:
            prefix=f"{old['pid']}-{old['creation_ticks']}-"
            oldroles.setdefault(old['service'],set()).update(w[len(prefix):] for w in recovered['ledger'].writers if w.startswith(prefix))
        require(all(isinstance(roles,(list,tuple)) and roles and len(set(roles))==len(roles) and set(roles)<=oldroles.get(fresh[pid]['service'],set()) for pid,roles in writer_roles.items()))
        writers={f"{fresh[pid]['pid']}-{fresh[pid]['creation_ticks']}-{role}" for pid,roles in writer_roles.items() for role in roles}
    require(bool(writers))
    path=Path(grant_path)
    require(path.name=='reauthorize-'+recovered['source_head']+'.grant')
    with path.open('xb') as stream:
        stream.write(json.dumps(request,sort_keys=True).encode());stream.flush();os.fsync(stream.fileno())
    ledger=ProductionAcknowledgements(journal,sorted(writers))
    ledger.commands={token:dict(row) for token,row in recovered['ledger'].commands.items()}
    broker=WriterBroker(ledger,credentials,fresh,verify_native,retention,server_epoch=server_epoch,
                       endpoint=endpoint,generation=request['generation'],parent_head=request['source_head'])
    # Empty ticket state and fresh explicit issuance/seal/registration are required.
    # No old CID or credential is unfenced here.
    return broker


def expose_readonly_after_quarantined_load(client, *, verify_scope, bootstrap_user):
    """Inactive bootstrap seam, not production startup or writer activation.

    Redis7.4.9's AOF EXEC rechecks the default user's permissions. Narrow replay
    permissions are allowed only with default authentication OFF and TCP port0.
    One EXEC restores normal default fencing and revokes bootstrap before another
    client can execute. Complete integrity validation and fresh writer authorization
    remain separate mandatory gates after the endpoint is read-only reachable.
    """
    require(verify_scope() is not False)
    configuration=client.config_get('port')
    require(isinstance(configuration,dict) and set(configuration)=={'port'} and
            (configuration['port']=='0' or type(configuration['port']) is int and configuration['port']==0))
    loading=client.info('persistence').get('loading')
    require(type(loading) is int and loading==0)
    require(isinstance(bootstrap_user,str) and re.fullmatch('[A-Za-z0-9_-]{1,80}',bootstrap_user) and bootstrap_user!='default')
    policy=client.acl_getuser('default')
    require(isinstance(policy,dict) and {'flags','passwords','categories','selectors','commands'}<=set(policy))
    require(isinstance(policy['flags'],list) and 'off' in policy['flags'] and 'on' not in policy['flags'] and 'nopass' not in policy['flags'] and policy['passwords']==[])
    require(policy.get('categories')==['-@all'] and policy.get('selectors')==[] and
            set(policy.get('commands',()))<= {'+xclaim','+xgroup|setid'})
    pipe=client.pipeline(transaction=True)
    pipe.execute_command('ACL','SETUSER','default','off','resetpass','-@all',
                         '+ping','+info','+client|id','+client|list')
    pipe.execute_command('CONFIG','SET','port','6379')
    pipe.execute_command('ACL','SETUSER',bootstrap_user,'off','resetpass','-@all')
    replies=pipe.execute()
    require(isinstance(replies,(list,tuple)) and len(replies)==3 and all(value is True or value==b'OK' or value=='OK' for value in replies))
    require(verify_scope() is not False)
    return {'state':'READ_ONLY_VERIFICATION_REQUIRED','writers_authorized':False}
