"""Default-off Redis accounting seam. No environment flag or startup activation.

Managed clients pin one physical connection and never implicitly replay mutations.
A native identity verifier, coordinator ledger and expected server epoch are supplied
by a separately reviewed bootstrap. Existing services use their unchanged factories.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import math
import re
import uuid
from contextlib import contextmanager
from redis.asyncio import Redis
from redis.asyncio.connection import Connection
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ResponseError


class AccountingError(RuntimeError):
    pass


class AmbiguousMutation(AccountingError):
    pass


MUTATIONS = {'XADD':'APPEND_WITH_POSSIBLE_RETENTION', 'LPUSH':'LIST_INSERT',
             'BRPOP':'DESTRUCTIVE_LIST_DELIVERY', 'SET':'VALUE_AND_EXPIRY',
             'XGROUP CREATE':'GROUP_CREATE', 'XREADGROUP':'GROUP_DELIVERY',
             'XACK':'PENDING_ACK', 'XAUTOCLAIM':'OWNERSHIP_AND_DELIVERY_COUNT',
             'XCLAIM':'OWNERSHIP_AND_DELIVERY_COUNT'}
READS = {'PING','LLEN','EXISTS','XLEN','XRANGE','XREVRANGE','XPENDING','XINFO STREAM',
         'XINFO GROUPS','XINFO CONSUMERS','GET','TYPE','PTTL','TIME','WAITAOF'}


def wire(value):
    if isinstance(value,bytes):return value
    if isinstance(value,str):return value.encode()
    if type(value) is int:return str(value).encode()
    if type(value) is float and math.isfinite(value):return str(value).encode()
    raise AccountingError('Command argument type unavailable')


def command(args):
    if not args:raise AccountingError('Empty Redis operation')
    parts=wire(args[0]).decode('ascii').upper().split()
    if parts==['XGROUP'] and len(args)>1:
        parts.append(wire(args[1]).decode('ascii').upper());tail=args[2:]
    else:tail=args[1:]
    name=' '.join(parts)
    if name not in MUTATIONS and name not in READS:
        raise AccountingError('Redis operation outside audited adapter scope')
    values=[wire(v) for v in tail]
    if len(values)>1024 or sum(map(len,values))>4*1024*1024:
        raise AccountingError('Command evidence outside bound')
    return name,values


def reply_bytes(value):
    """Type-tagged bounded replies; never persist free-text provider errors."""
    count=0
    def encode(v,depth=0):
        nonlocal count
        count+=1
        if count>20000 or depth>20:raise AccountingError('Reply outside structure bound')
        if v is None:return ['null']
        if isinstance(v,bytes):return ['bytes',v.hex()]
        if isinstance(v,str):return ['string',v]
        if type(v) is bool:return ['boolean',v]
        if type(v) is int:return ['integer',v]
        if isinstance(v,(list,tuple)):return ['array',[encode(x,depth+1) for x in v]]
        if isinstance(v,dict):
            pairs=[[encode(k,depth+1),encode(x,depth+1)] for k,x in v.items()]
            return ['map',sorted(pairs,key=lambda p:json.dumps(p[0],sort_keys=True))]
        raise AccountingError('Reply type unavailable')
    result=json.dumps(encode(value),ensure_ascii=True,separators=(',',':')).encode()
    if len(result)>4*1024*1024:raise AccountingError('Reply outside byte bound')
    return result


def identity(value):
    fields={'pid','creation_ticks','service','command_sha256','repository_sha256'}
    if not isinstance(value,dict) or set(value)!=fields:
        raise AccountingError('Native identity evidence incomplete')
    if any(type(value[k]) is not int or value[k]<=0 for k in ('pid','creation_ticks')):
        raise AccountingError('Native identity invalid')
    if value['service'] not in ('event-log','api','sentinel','collector','entities','discord','fixture'):
        raise AccountingError('Writer service not allowlisted')
    if any(not isinstance(value[k],str) or not re.fullmatch('[0-9a-f]{64}',value[k]) for k in ('command_sha256','repository_sha256')):
        raise AccountingError('Native ownership fingerprint unavailable')
    return dict(value)


class Runtime:
    """One process's managed writers. A future controller must fence ALL processes.

    Connection inventory equality is required, not CLIENT name claims. Cross-process
    IPC and server ACL enforcement are activation prerequisites, not granted here.
    """
    def __init__(self,ledger,verify_identity,*,endpoint,server_epoch,roles,credentials=None):
        if not isinstance(server_epoch,str) or not re.fullmatch('[0-9a-f]{40}',server_epoch):
            raise AccountingError('Expected Redis server epoch required')
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint):raise AccountingError('Endpoint identity invalid')
        if not roles or any(not re.fullmatch('[a-z][a-z-]{1,60}',r) for r in roles):raise AccountingError('Writer role scope unavailable')
        self.ledger=ledger;self.verify_identity=verify_identity;self.owner=identity(verify_identity())
        service_roles={'event-log':{'redis-streams'},'api':{'api-manual-queue'},'sentinel':{'redis-streams','sentinel-manual-consumer'},'collector':{'redis-streams','collector-consumer'},'entities':{'entity-consumer'},'discord':{'discord-alerts'}}
        if self.owner['service']!='fixture' and not set(roles)<=service_roles[self.owner['service']]:raise AccountingError('Writer role contradicts native service')
        self.endpoint=endpoint;self.server_epoch=server_epoch;self.roles=frozenset(roles)
        if credentials is None and self.owner['service']!='fixture':raise AccountingError('Production writer credential enforcement required')
        self.credentials=credentials
        self.fenced=False;self.held=False;self.generation=1;self.clients=set();self.inflight=set()

    def check(self,client,*,read_only=False):
        if identity(self.verify_identity())!=self.owner:raise AccountingError('Native PID/creation/ownership changed')
        if (self.fenced and not read_only) or self.held or client.route_generation!=self.generation:
            raise AccountingError('Writer or stale connection generation fenced')
        if client.role not in self.roles:raise AccountingError('Unregistered writer role')

    async def quiesce(self,timeout=10):
        self.fenced=True  # No new command or registration can cross this edge.
        deadline=asyncio.get_running_loop().time()+timeout
        while self.inflight:
            if asyncio.get_running_loop().time()>=deadline:
                self.held=True;raise AccountingError('Writer drain timed out; retain current state')
            await asyncio.sleep(.01)
        return self.ledger.settled()  # Unknown replies still prohibit routing.

    def verify_connections(self,observed_ids):
        expected={c.connection_id for c in self.clients if c.connection_id is not None and not c.retired}
        if any(type(i) is not int or i<=0 for i in observed_ids) or len(set(observed_ids))!=len(observed_ids) or set(observed_ids)!=expected:
            raise AccountingError('Unknown or missing physical Redis connection')
        if not self.fenced or self.inflight:raise AccountingError('Writers not quiesced')
        self.ledger.settled()
        return sorted(expected)

    async def retire_and_reauthorize(self,*,endpoint,server_epoch):
        if not self.fenced or self.held or self.inflight:raise AccountingError('No verified drained route boundary')
        self.ledger.settled()
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint) or not re.fullmatch('[0-9a-f]{40}',server_epoch):
            raise AccountingError('New route evidence invalid')
        for client in list(self.clients):await client.aclose()
        self.endpoint=endpoint;self.server_epoch=server_epoch;self.generation+=1
        # New clients may register/read while fenced; only a verified coordinator
        # exit can explicitly resume mutations. Old objects remain stale.

    def resume_verified(self):
        if not self.fenced or self.held or self.inflight:raise AccountingError('Writer boundary not verified')
        self.ledger.settled();self.fenced=False


class FencedConnection(Connection):
    async def connect(self):
        if getattr(self,'accounting_bound',False) and not self.is_connected:
            raise AccountingError('Bound physical connection cannot reconnect implicitly')
        await super().connect()


class ManagedRedis(Redis):
    """Real redis-py command API with explicit no-retry pinned connection semantics."""
    def attach(self,runtime,role):
        if role not in runtime.roles:raise AccountingError('Unregistered writer role')
        self.runtime=runtime;self.role=role;self.route_generation=runtime.generation
        self.connection_id=None;self.retired=False;self.accounting_lock=asyncio.Lock()
        self.writer=f"{runtime.owner['pid']}-{runtime.owner['creation_ticks']}-{role}"
        if self.writer not in runtime.ledger.writers:raise AccountingError('Writer absent from durable ledger scope')
        runtime.check(self,read_only=True);runtime.clients.add(self);return self

    async def _physical_binding(self):
        client_id=await Redis.execute_command(self,'CLIENT ID')
        server=await Redis.execute_command(self,'INFO','server')
        epoch=server.get('run_id',server.get(b'run_id'))
        if isinstance(epoch,bytes):epoch=epoch.decode('ascii')
        if epoch!=self.runtime.server_epoch or type(client_id) is not int or client_id<=0:
            self.runtime.held=True;raise AccountingError('Unexpected Redis server/connection identity')
        if self.connection_id is not None and client_id!=self.connection_id:
            self.runtime.held=True;raise AccountingError('Implicit reconnection generation rejected')
        if self.connection_id is None:
            self.connection.accounting_bound=True
            confirmation=await Redis.execute_command(self,'CLIENT ID')
            if confirmation!=client_id:
                self.runtime.held=True;raise AccountingError('Physical binding changed during registration')
            self.runtime.check(self,read_only=True)
            self.runtime.ledger.register_connection(self.writer,self.runtime.owner,client_id,epoch,self.route_generation)
            if self.runtime.credentials is not None:
                try:self.runtime.credentials.seal(self.credential_ticket,self.runtime.owner,self.role,self.route_generation,epoch,client_id)
                except BaseException:
                    self.runtime.held=True
                    raise
            self.connection_id=client_id

    async def execute_command(self,*args,**options):
        name,values=command(args)
        async with self.accounting_lock:
            self.runtime.check(self,read_only=name in READS)
            if self.retired:raise AccountingError('Retired client cannot dispatch')
            await self._physical_binding()
            self.runtime.check(self,read_only=name in READS)  # Fence could arrive during registration IO.
            if name in READS:return await Redis.execute_command(self,*args,**options)
            token=self.runtime.ledger.begin_command(self.writer,name,values,self.connection_id,self.route_generation)
            self.runtime.inflight.add(token)
            try:
                reply=await Redis.execute_command(self,*args,**options)
                self.runtime.ledger.complete_command(token,reply,reply_bytes(reply),self.runtime.endpoint)
                return reply
            except ResponseError as exc:
                # This precise CREATE rejection is known to have no dataset effect.
                if name=='XGROUP CREATE' and str(exc).startswith('BUSYGROUP'):
                    try:self.runtime.ledger.reject_group_exists(token,self.runtime.endpoint)
                    except BaseException:
                        self.runtime.held=True
                        raise AmbiguousMutation('Durable rejection receipt uncertain') from None
                    raise
                self.runtime.held=True
                raise AmbiguousMutation('Mutation reply uncertified; no automatic replay') from None
            except BaseException as exc:
                self.runtime.held=True
                if isinstance(exc,asyncio.CancelledError):raise
                raise AmbiguousMutation('Mutation outcome or durable acknowledgement uncertain') from None
            finally:self.runtime.inflight.discard(token)

    async def aclose(self,*args,**kwargs):
        async with self.accounting_lock:
            await Redis.aclose(self,*args,**kwargs)
            if self.connection_id is not None and not self.retired:
                self.runtime.ledger.retire_connection(self.writer,self.connection_id,self.route_generation)
            self.retired=True

    def pipeline(self,*args,**kwargs):raise AccountingError('Pipelines require separate physical-attempt certification')
    def client(self):raise AccountingError('Unregistered child client forbidden')


class ClientFactory:
    def __init__(self):self.runtime=None;self.issued=False
    def configure(self,runtime):
        if self.issued or self.runtime is not None:raise AccountingError('Live factory replacement forbidden')
        self.runtime=runtime
    def from_url(self,url,*,role,legacy_factory=Redis.from_url,**kwargs):
        self.issued=True
        if self.runtime is None:return legacy_factory(url,**kwargs)
        if role not in self.runtime.roles:raise AccountingError('Unregistered writer role')
        ticket=None
        if self.runtime.credentials is not None:
            ticket=self.runtime.credentials.issue(self.runtime.owner,role,self.runtime.generation,self.runtime.server_epoch)
            kwargs.update({k:ticket[k] for k in ('username','password')})
        kwargs.update(retry_on_timeout=False,retry=Retry(NoBackoff(),0),health_check_interval=0,connection_class=FencedConnection)
        client=ManagedRedis.from_url(url,single_connection_client=True,**kwargs)
        # URL query options take precedence in redis-py. Validate final pool options.
        config=client.connection_pool.connection_kwargs
        if client.connection_pool.connection_class is not FencedConnection or config.get('retry_on_timeout') or config.get('retry').get_retries()!=0:
            raise AccountingError('Implicit driver retries forbidden for managed mutations')
        if ticket is not None and any(config.get(k)!=ticket[k] for k in ('username','password')):raise AccountingError('URL overrides sealed credentials')
        if ticket is not None:
            target=ticket['target']
            if config.get('host') not in ('127.0.0.1','localhost') or int(config.get('port',0))!=target['port'] or config.get('db',0)!=0:raise AccountingError('Managed endpoint differs from sealed credential target')
        client.credential_ticket=ticket
        return client.attach(self.runtime,role)


FACTORY=ClientFactory()  # No production code configures it in this checkpoint.

def redis_client(url,*,role,legacy_factory=Redis.from_url,**kwargs):
    return FACTORY.from_url(url,role=role,legacy_factory=legacy_factory,**kwargs)
