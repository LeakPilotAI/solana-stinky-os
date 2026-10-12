"""Dormant service bootstrap. A protected grant never falls back to legacy Redis.

Grants are trusted controller capabilities, not a substitute for independently
certifying capacity/recovery/ownership. Production activation requires separate
approval. Normal services have no grant option/environment and remain unchanged.
"""
from __future__ import annotations
import hashlib,hmac,json,os,re,subprocess,time
from pathlib import Path
from stinky_core.transport.redis_accounting import AccountingError,Runtime,identity
from scripts.redis_evidence_archive import UserProtection
from scripts.redis_writer_broker import PipeProxy,PinnedRedisScope
from scripts.redis_production_adapters import native_writer_verifier,writer_id

ENV='GENESIS_PROTECTED_REDIS_GRANT'
ROLES={'event-log':{'redis-streams'},'api':{'api-manual-queue'},
       'sentinel':{'redis-streams'},'collector':{'redis-streams','collector-consumer'},
       'entities':{'entity-consumer'}}

def sign(body):
    key=bytes.fromhex(body['authkey'])
    return hmac.new(key,json.dumps(body,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

def install_grant(factory,grant,*,verify_owner,verify_scope,now=None):
    """Explicit trusted-controller initialization before the first client exists."""
    fields={'schema','owner','broker_identity','pipe','authkey','server_epoch','endpoint',
            'generation','roles','pins','expires_at','admission','signature'}
    try:
        if not isinstance(grant,dict) or set(grant)!=fields or grant['schema']!='genesis-protected-startup-v1':raise ValueError()
        body={k:v for k,v in grant.items() if k!='signature'}
        if not isinstance(body['authkey'],str) or not re.fullmatch('[0-9a-f]{64}',body['authkey']):raise ValueError()
        if not hmac.compare_digest(sign(body),grant['signature']):raise ValueError()
        owner=identity(verify_owner())
        if identity(body['owner'])!=owner:raise ValueError()
        now=int(time.time()) if now is None else now
        if type(body['expires_at']) is not int or not now<body['expires_at']<=now+120:raise ValueError()
        roles=body['roles']
        if not isinstance(roles,list) or not roles or len(set(roles))!=len(roles) or not set(roles)<=ROLES.get(owner['service'],set()):raise ValueError()
        admission=body['admission']
        if set(admission)!={'capacity','custody','recovery','retention','manifest_sha256','brpop'}:raise ValueError()
        if any(admission[k]!='GREEN' for k in ('capacity','custody','recovery','retention')):raise ValueError()
        if admission['brpop']!='REJECTED' or not re.fullmatch('[0-9a-f]{64}',admission['manifest_sha256']):raise ValueError()
        if type(body['generation']) is not int or body['generation']<=0:raise ValueError()
        if not isinstance(body['pipe'],str) or not body['pipe'].startswith('\\\\.\\pipe\\genesis-') or len(body['pipe'])>200:raise ValueError()
        pin=PinnedRedisScope(**body['pins']);verify_scope(pin)
        peer=tuple(body['broker_identity'])
        proxy=PipeProxy(body['pipe'],bytes.fromhex(body['authkey']),[writer_id(owner,r) for r in roles],server_identity=peer)
        runtime=Runtime(proxy,verify_owner,endpoint=body['endpoint'],server_epoch=body['server_epoch'],roles=roles,credentials=proxy)
        runtime.generation=body['generation']
        factory.configure(runtime)
        return runtime
    except (ValueError,TypeError,KeyError,AttributeError):
        raise AccountingError('Protected startup grant invalid, stale or uncertified; no legacy fallback') from None

def install_from_path(factory,path):
    import start_genesis as launcher
    from scripts.guarded_redis_migration import NativePause
    root=launcher.ROOT/'logs'/'protected-redis-grants';path=Path(path)
    if (path.is_symlink() or root.is_symlink() or path.parent.resolve()!=root.resolve()
        or not re.fullmatch('[A-Za-z0-9_-]{1,80}\\.dpapi',path.name)):
        raise AccountingError('Protected grant outside reviewed directory')
    with path.open('rb') as stream:sealed=stream.read(65537)
    if not 0<len(sealed)<=65536:raise AccountingError('Protected grant exceeds bound')
    plain=UserProtection().open(sealed)
    if len(plain)>65536:raise AccountingError('Protected grant plaintext exceeds bound')
    try:grant=json.loads(plain)
    except (ValueError,UnicodeError):raise AccountingError('Protected grant malformed') from None
    def scope(pin):
        result=subprocess.run([launcher.find_docker(),'inspect',pin.container_id],capture_output=True,text=True,timeout=5)
        if result.returncode or len(result.stdout)>262144:raise AccountingError('Protected native Redis scope unavailable')
        pin(json.loads(result.stdout))
    return install_grant(factory,grant,verify_owner=native_writer_verifier(launcher,NativePause()),verify_scope=scope)
