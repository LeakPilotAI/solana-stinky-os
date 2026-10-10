"""Ledger bridge for inactive production adapters; coordinator scope stays isolated.

New nonstream/claim receipts are settled explicitly. Actual state preservation still
requires the coordinator's complete semantic source/candidate recovery proof. No
receipt count substitutes for snapshot continuity, and trimmed XADD receipts are
NOT silently exempted from the existing payload-membership gate.
"""
from __future__ import annotations
import hashlib,json,os,re,threading
from pathlib import Path
from scripts.redis_migration_coordinator import Acknowledgements
from scripts.redis_stream_integrity import framed_hash
from stinky_core.transport.redis_accounting import MUTATIONS,AccountingError,identity


class DurableJournal:
    def __init__(self,path,*,max_bytes=64*1024*1024):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=self.path.open('xb');self.max_bytes=max_bytes
        self.sequence=0;self.previous='0'*64;self.bytes=0;self.lock=threading.RLock();self.failed=False
    def persist(self,record):
        with self.lock:
            if self.failed:raise AccountingError('Journal failed; new dispatch prohibited')
            body={'sequence':self.sequence+1,'previous_sha256':self.previous,'record':record}
            encoded=json.dumps(body,sort_keys=True,separators=(',',':')).encode()
            if len(encoded)>4*1024*1024 or self.bytes+len(encoded)+1>self.max_bytes:
                raise AccountingError('Durable journal capacity exceeded; no new mutation permitted')
            try:
                self.stream.write(encoded+b'\n');self.stream.flush();os.fsync(self.stream.fileno())
            except BaseException:
                self.failed=True
                raise
            self.sequence+=1;self.bytes+=len(encoded)+1;self.previous=hashlib.sha256(encoded).hexdigest()
    def close(self):self.stream.close()


def read_records(path,*,expected_head,max_bytes=64*1024*1024):
    if not isinstance(expected_head,str) or not re.fullmatch('[0-9a-f]{64}',expected_head):raise AccountingError('Trusted journal head required')
    with Path(path).open('rb') as stream:data=stream.read(max_bytes+1)
    if len(data)>max_bytes or (data and not data.endswith(b'\n')):
        raise AccountingError('Journal truncated or outside bound; unresolved evidence retained')
    previous='0'*64;records=[]
    for sequence,line in enumerate(data.splitlines(),1):
        try:body=json.loads(line)
        except (ValueError,UnicodeError):raise AccountingError('Journal malformed') from None
        if set(body)!={'sequence','previous_sha256','record'} or body['sequence']!=sequence or body['previous_sha256']!=previous:
            raise AccountingError('Journal ordering/integrity mismatch')
        previous=hashlib.sha256(line).hexdigest();records.append(body['record'])
    if previous!=expected_head:raise AccountingError('Journal boundary head mismatch')
    return records


def append_fields(args):
    if len(args)<4:raise AccountingError('Incomplete stream append')
    # Redis-py emits key,[MAXLEN|MINID [~|=] threshold [LIMIT n]],id,field,value.
    i=1
    if args[i].upper() in (b'MAXLEN',b'MINID'):
        i+=1
        if args[i] in (b'~',b'='):i+=1
        if i>=len(args) or not args[i].isdigit():raise AccountingError('Append retention syntax invalid')
        i+=1
        if i<len(args) and args[i].upper()==b'LIMIT':
            i+=2
    if i>=len(args) or (args[i]!=b'*' and not re.fullmatch(rb'[0-9]+-[0-9]+',args[i])):
        raise AccountingError('Append ID syntax unavailable')
    fields=args[i+1:]
    if not fields or len(fields)%2:raise AccountingError('Incomplete stream payload')
    return fields


def validate_command(name,args):
    if name not in MUTATIONS or not args or any(not isinstance(v,bytes) for v in args):raise AccountingError('Unaccounted mutation')
    if name=='XADD':append_fields(args)
    if name=='LPUSH' and len(args)<2:raise AccountingError('Empty list insertion')
    if name=='BRPOP':raise AccountingError('Destructive list delivery requires durable processing receipt; activation forbidden')
    if name=='SET':
        if len(args)!=4 or args[2].upper()!=b'EX' or not args[3].isdigit() or not 0<int(args[3])<=172800:
            raise AccountingError('Only audited bounded-EX SET supported')
    if name=='XAUTOCLAIM' and len(args)<5:raise AccountingError('Claim identity incomplete')
    if name=='XCLAIM' and len(args)<5:raise AccountingError('Claim identity incomplete')
    if name=='XACK' and len(args)<3:raise AccountingError('Acknowledgement identity incomplete')
    if name=='XGROUP CREATE' and len(args)<3:raise AccountingError('Group identity incomplete')
    if name=='XREADGROUP':
        upper=[v.upper() for v in args]
        if upper.count(b'STREAMS')!=1 or upper[:1]!=[b'GROUP']:raise AccountingError('Group delivery syntax unsupported')
        if b'BLOCK' in upper:
            i=upper.index(b'BLOCK')
            if i+1>=len(args) or not args[i+1].isdigit() or not 0<int(args[i+1])<=60000:raise AccountingError('Unbounded group delivery forbidden')


class ProductionAcknowledgements(Acknowledgements):
    """Registered physical-attempt receipts, including list and claim operations."""
    def __init__(self,journal,writers):
        super().__init__(journal,writers);self.bindings={}
    def register_connection(self,writer,owner,client_id,server_epoch,generation):
        with self.lock:
            if writer not in self.writers or type(client_id) is not int or client_id<=0 or type(generation) is not int or generation<=0:
                raise AccountingError('Unregistered connection')
            owner=identity(owner)
            if not re.fullmatch('[0-9a-f]{40}',server_epoch):raise AccountingError('Server epoch unavailable')
            key=(writer,client_id,generation)
            binding={'writer':writer,'owner':owner,'client_id':client_id,'server_epoch':server_epoch,'generation':generation,'active':True}
            if any(b['active'] and b['client_id']==client_id and b['server_epoch']==server_epoch for b in self.bindings.values()):raise AccountingError('Physical connection already registered')
            self.journal.persist({'stage':'CONNECTION_REGISTERED',**binding});self.bindings[key]=binding
    def retire_connection(self,writer,client_id,generation):
        with self.lock:
            key=(writer,client_id,generation);binding=self.bindings[key]
            self.journal.persist({'stage':'CONNECTION_RETIRED','writer':writer,'client_id':client_id,'generation':generation})
            self.bindings[key]={**binding,'active':False}
    def begin_command(self,writer,name,args,client_id,generation):
        with self.lock:
            validate_command(name,args)
            if len(self.commands)>=50000:raise AccountingError('Acknowledgement ledger capacity exceeded')
            if not self.bindings.get((writer,client_id,generation),{}).get('active'):
                raise AccountingError('Mutation connection unregistered or retired')
            token=len(self.commands)+1
            row={'token':token,'writer':writer,'command':name,'classification':MUTATIONS[name],
                 'args_sha256':framed_hash(args),'connection_id':client_id,'generation':generation,'state':'ISSUED'}
            if name=='XADD':
                fields=append_fields(args);row.update(key_sha256=hashlib.sha256(args[0]).hexdigest(),payload_sha256=framed_hash(fields),field_count=len(fields)//2)
            else:row['operation']=name
            self.journal.persist({'stage':'COMMAND_INTENT',**row});self.commands[token]=row;return token
    def complete_command(self,token,reply,serialized,endpoint):
        with self.lock:
            row=self.commands[token]
            if row['state']!='ISSUED' or not isinstance(serialized,bytes) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint):raise AccountingError('Unsettled or invalid command reply')
            validate_reply(row['command'],reply)
            changed={**row,'state':'ACKNOWLEDGED','endpoint_id':endpoint,'reply_sha256':hashlib.sha256(serialized).hexdigest()}
            if row['command']=='XADD':
                value=reply.decode('ascii') if isinstance(reply,bytes) else reply
                if not isinstance(value,str) or not re.fullmatch('[0-9]+-[0-9]+',value):raise AccountingError('Stream acknowledgement malformed')
                changed['entry_id']=value
            self.journal.persist({'stage':'COMMAND_REPLY',**changed});self.commands[token]=changed
    def reject_group_exists(self,token,endpoint):
        with self.lock:
            row=self.commands[token]
            if row['command']!='XGROUP CREATE' or row['state']!='ISSUED':raise AccountingError('Rejection not proven nonmutating')
            if not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint):raise AccountingError('Endpoint identity unavailable')
            changed={**row,'state':'ACKNOWLEDGED','endpoint_id':endpoint,'reply_sha256':hashlib.sha256(b'BUSYGROUP_NO_EFFECT').hexdigest(),'outcome':'REJECTED_NO_EFFECT','error_code':'BUSYGROUP'}
            self.journal.persist({'stage':'COMMAND_REPLY',**changed});self.commands[token]=changed


def writer_id(owner,role):return f"{owner['pid']}-{owner['creation_ticks']}-{role}"

def native_writer_verifier(launcher,adapter):
    """Read-only startup ownership proof plus per-command native PID reuse checks.

    The adapter must expose read-only open/creation/image/close operations. No pause,
    process termination or container authority is invoked by this function.
    """
    import os
    from scripts import genesis_process_diagnostics as diagnostics, safe_genesis_start as safe
    pid=os.getpid();snapshot=diagnostics.capture_native(launcher,adapter)
    nodes={n['pid']:n for n in snapshot['nodes']}
    if pid not in nodes:raise AccountingError('Current writer is not in verified Genesis ancestry')
    node=nodes[pid];ancestor=pid
    for _ in range(24):
        current=nodes.get(ancestor)
        if current is None:raise AccountingError('Writer ancestry unavailable')
        if current['role'].startswith('supervisor:'):
            service=current['role'].split(':',1)[1];break
        ancestor=current['parent_pid']
    else:raise AccountingError('Writer ancestry exceeds bound')
    owner=identity({'pid':pid,'creation_ticks':node['creation_ticks'],'service':service,
                    'command_sha256':node['command_sha256'],
                    'repository_sha256':hashlib.sha256(str(launcher.ROOT.resolve()).encode()).hexdigest()})
    def verify():
        ticks,image=diagnostics.native_identity(adapter,pid)
        if os.getpid()!=pid or ticks!=node['creation_ticks'] or safe.windows_path(image)!=node['image_path']:
            raise AccountingError('Native writer PID reuse or image change')
        return dict(owner)
    verify.startup_snapshot=snapshot
    return verify


def verify_default_write_fence(policy):
    """Require complete redis-py ACL GETUSER evidence, including selectors.

    Categories and commands are separate in the installed driver. Read-only
    command names without the -@all baseline or with extra selectors are unsafe.
    """
    if not isinstance(policy,dict):raise AccountingError('Complete server ACL evidence unavailable')
    commands=policy.get('commands');categories=policy.get('categories');selectors=policy.get('selectors');flags=policy.get('flags')
    allowed={'+ping','+info','+client|id','+client|list'}
    if categories!=['-@all'] or selectors!=[] or not isinstance(commands,list) or any(not isinstance(t,str) or t not in allowed for t in commands):
        raise AccountingError('Unregistered Redis principals retain mutation authority')
    if not isinstance(flags,list) or ('on' in flags)==('off' in flags):raise AccountingError('Default principal state unavailable')
    return True


def validate_reply(name,reply):
    if name in ('LPUSH','XACK'):
        if type(reply) is not int or reply<0 or (name=='LPUSH' and reply==0):raise AccountingError('Mutation count reply malformed')
    elif name in ('SET','XGROUP CREATE'):
        if reply is not True:raise AccountingError('Mutation success reply malformed')
    elif name=='BRPOP':
        if reply is not None and (not isinstance(reply,(list,tuple)) or len(reply)!=2 or any(not isinstance(v,(bytes,str)) for v in reply)):
            raise AccountingError('List delivery reply incomplete')
    elif name=='XAUTOCLAIM':
        if not isinstance(reply,(list,tuple)) or len(reply)!=3:raise AccountingError('Claim reply incomplete')
        cursor=reply[0].decode() if isinstance(reply[0],bytes) else reply[0]
        if not isinstance(cursor,str) or not re.fullmatch('[0-9]+-[0-9]+',cursor):raise AccountingError('Claim cursor malformed')
        if not isinstance(reply[1],(list,tuple)) or not isinstance(reply[2],(list,tuple)):raise AccountingError('Claim ownership/deletion reply incomplete')
    elif name in ('XREADGROUP','XCLAIM'):
        if reply is not None and not isinstance(reply,(list,tuple)):raise AccountingError('Group delivery reply malformed')


def expected_writer_owners(runtimes):
    return {writer:dict(runtime.owner) for runtime in runtimes for writer in runtime.ledger.writers}


async def quiesce_registered(runtimes,*,timeout=10):
    """Coordinator bridge: fence every supplied actor before draining any of them.

    Remote/native actor discovery is required by the activation procedure. This
    function never treats an omitted actor or an anonymous peer as registered.
    """
    import asyncio
    if not runtimes:raise AccountingError('No registered writers')
    owners=expected_writer_owners(runtimes)
    if len(owners)!=sum(len(r.ledger.writers) for r in runtimes):raise AccountingError('Duplicate logical writer registration')
    for r in runtimes:r.fenced=True
    try:
        results=await asyncio.gather(*(r.quiesce(timeout) for r in runtimes))
    except BaseException:
        for r in runtimes:r.held=True
        raise
    return {'writers':sorted(owners),'settled':sum(results),'writer_owners':owners}

class SealedCredentials:
    """Isolated-only server enforcement, reusable protocol for reviewed activation.

    Each physical connection authenticates to a unique initially read-only user.
    Seal verifies exactly one CID, removes all reusable passwords, then grants the
    audited role commands. An unregistered clone cannot authenticate afterward.
    No production Redis scope is accepted by this certification implementation.
    """
    READ_RULES=['+ping','+info','+client|id','+llen','+exists','+xlen','+xrange','+xrevrange','+xpending','+xinfo','+get','+type','+pttl','+time','+waitaof']
    ROLE_COMMANDS={
        'redis-streams':['+xadd','+xgroup|create','+xreadgroup','+xack'],
        'collector-consumer':['+xgroup|create','+xreadgroup','+xack'],
        'entity-consumer':['+xgroup|create','+xreadgroup','+xack','+xautoclaim','+xclaim'],
        'api-manual-queue':['+lpush'], 'sentinel-manual-consumer':[],
        'discord-alerts':['+xgroup|create','+xreadgroup','+xack','+set']}
    def __init__(self,admin,scope,verify_owner,journal):
        self.admin=admin;self.scope=scope;self.verify_owner=verify_owner;self.journal=journal
        self.tickets={};self.fenced=False
    def check_scope(self):
        from scripts.redis_migration_coordinator import verify_isolated_scope
        verify_isolated_scope(self.scope())
    def checked_admin(self):
        records=self.scope()
        from scripts.redis_migration_coordinator import verify_isolated_scope
        verify_isolated_scope(records)
        c=self.admin();config=c.connection_pool.connection_kwargs
        matches=[r for r in records if r['State']['Running'] and any(int(p['HostPort'])==int(config.get('port',0)) for p in r['HostConfig']['PortBindings']['6379/tcp'])]
        if config.get('host') not in ('127.0.0.1','localhost') or config.get('db',0)!=0 or len(matches)!=1:
            c.close();raise AccountingError('Credential admin endpoint is not the owned isolated container')
        return c

    def issue(self,owner,role,generation,epoch):
        import secrets,uuid
        self.check_scope()
        if identity(self.verify_owner())!=owner or role not in self.ROLE_COMMANDS:raise AccountingError('Credential owner or role unavailable')
        if role=='sentinel-manual-consumer':raise AccountingError('Destructive list consumer activation requires durable processing protocol')
        if len(self.tickets)>=2048:raise AccountingError('Credential retention capacity reached')
        c=self.checked_admin()
        try:
            if c.info('server')['run_id']!=epoch:raise AccountingError('Credential endpoint epoch differs')
            verify_default_write_fence(c.acl_getuser('default'))
            user='genesis-c66-'+uuid.uuid4().hex;password=secrets.token_hex(32)
            c.execute_command('ACL','SETUSER',user,'reset','on','>'+password,'~*','-@all',*self.READ_RULES)
        finally:c.close()
        self.tickets[user]={'owner':dict(owner),'role':role,'generation':generation,'epoch':epoch,'cid':None}
        self.journal.persist({'stage':'CONNECTION_CREDENTIAL_ISSUED','principal':user,'owner':owner,'role':role,'generation':generation,'server_epoch':epoch})
        return {'username':user,'password':password,'target':{'host':c.connection_pool.connection_kwargs['host'],'port':int(c.connection_pool.connection_kwargs['port']),'db':0}}
    def seal(self,ticket,owner,role,generation,epoch,cid):
        self.check_scope();user=ticket['username'];record=self.tickets.get(user)
        if not record or record!={'owner':owner,'role':role,'generation':generation,'epoch':epoch,'cid':None} or identity(self.verify_owner())!=owner:
            raise AccountingError('Credential registration mismatch')
        c=self.checked_admin()
        try:
            if c.info('server')['run_id']!=epoch:raise AccountingError('Credential epoch changed')
            verify_default_write_fence(c.acl_getuser('default'))
            # Remove reusable credentials BEFORE observing the unique CID. A
            # clone cannot authenticate in a count-then-grant race window.
            c.execute_command('ACL','SETUSER',user,'resetpass','-@all',*self.READ_RULES)
            matches=[row for row in c.client_list() if row.get('user')==user]
            if len(matches)!=1 or int(matches[0]['id'])!=cid:raise AccountingError('Cloned or missing credential connection')
            rules=[] if self.fenced else self.ROLE_COMMANDS[role]
            c.execute_command('ACL','SETUSER',user,'resetpass','-@all',*self.READ_RULES,*rules)
            policy=c.acl_getuser(user)
            if policy['passwords'] or 'nopass' in policy['flags']:raise AccountingError('Reusable writer credentials remain')
        finally:c.close()
        self.journal.persist({'stage':'CONNECTION_CREDENTIAL_SEALED','principal':user,'client_id':cid,'generation':generation,'server_epoch':epoch})
        record['cid']=cid
    def set_fenced(self,value):
        self.check_scope();c=self.checked_admin()
        try:
            epoch=c.info('server')['run_id'];verify_default_write_fence(c.acl_getuser('default'))
            peers={row.get('user'):int(row['id']) for row in c.client_list()}
            for user,record in self.tickets.items():
                if record['epoch']!=epoch or record['cid'] is None:continue
                policy=c.acl_getuser(user)
                if policy is None:raise AccountingError('Registered credential disappeared')
                if value:
                    c.execute_command('ACL','SETUSER',user,'-@all',*self.READ_RULES)
                elif peers.get(user)==record['cid']:
                    if identity(self.verify_owner())!=record['owner']:raise AccountingError('Credential owner PID reused')
                    c.execute_command('ACL','SETUSER',user,'-@all',*self.READ_RULES,*self.ROLE_COMMANDS[record['role']])
            self.journal.persist({'stage':'SERVER_WRITER_FENCE','fenced':bool(value),'server_epoch':epoch})
        finally:c.close()
        self.fenced=bool(value)
