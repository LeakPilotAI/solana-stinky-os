"""Strict semantic Redis recovery proof; raw DUMP fingerprints stay diagnostic.

Stream IDs and ordered field/value bytes, group cursors and every PEL owner,
absolute delivery time and delivery count are immutable comparison fields.
Only consumer seen/active activity clocks may reset during declared AOF replay.
Original values are retained in observations, never normalized or overwritten.
"""
from __future__ import annotations
import hashlib
import json
import re
from scripts.redis_snapshot_integrity import MAX_KEYS,MAX_KEY_BYTES,fingerprint

MAX_ENTRIES=50_000
MAX_GROUPS=1_000
MAX_CONSUMERS=1_000

READ = """
local version=string.match(redis.call('INFO','server'),'redis_version:([^\\r\\n]+)')
if version~='7.4.9' then return redis.error_reply('uncertified Redis stream metadata version') end
if redis.call('DBSIZE')>tonumber(ARGV[1]) then return redis.error_reply('key bound exceeded') end
local rows={}
local total=0
for _,key in ipairs(redis.call('KEYS','*')) do
 if (redis.call('MEMORY','USAGE',key) or 0)>tonumber(ARGV[2]) then return redis.error_reply('key byte bound exceeded') end
 local kind=redis.call('TYPE',key).ok
 local dump=redis.call('DUMP',key)
 total=total+#dump
 if total>tonumber(ARGV[2]) then return redis.error_reply('dataset byte bound exceeded') end
 local full={}
 if kind=='stream' then
  if redis.call('XLEN',key)>tonumber(ARGV[3]) then return redis.error_reply('stream entry bound exceeded') end
  local groups=redis.call('XINFO','GROUPS',key)
  if #groups>tonumber(ARGV[4]) then return redis.error_reply('group bound exceeded') end
  for _,g in ipairs(groups) do
   for i=1,#g,2 do
    if g[i]=='pending' and g[i+1]>tonumber(ARGV[3]) then return redis.error_reply('PEL bound exceeded') end
    if g[i]=='consumers' and g[i+1]>tonumber(ARGV[5]) then return redis.error_reply('consumer bound exceeded') end
   end
  end
  full=redis.call('XINFO','STREAM',key,'FULL','COUNT',tonumber(ARGV[3])+1)
 end
 table.insert(rows,{key,kind,dump,redis.call('PEXPIRETIME',key),full})
end
local now=redis.call('TIME')
return {tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000),rows}
"""

def fail(message):raise ValueError('Redis recovery proof invalid: '+message)

def pairs(value):
    if not isinstance(value,list) or len(value)%2:fail('malformed metadata pairs')
    result={}
    for key,item in zip(value[::2],value[1::2]):
        if not isinstance(key,bytes) or key in result:fail('duplicate/nonbyte metadata field')
        result[key]=item
    return result

def fields(value,required):
    result=pairs(value)
    if set(result)!=set(required):fail('unknown or missing metadata field')
    return result

def number(value,*,minimum=0,nullable=False):
    if value is None and nullable:return None
    if type(value)!=int or value<minimum:fail('invalid counter/clock')
    return value

def raw(value):
    if not isinstance(value,bytes):fail('evidence is not raw bytes')
    return value

def stream_id(value):
    value=raw(value)
    if not re.fullmatch(rb'[0-9]+-[0-9]+',value):fail('invalid stream ID')
    return value.decode('ascii')

def framed_hash(values):
    digest=hashlib.sha256()
    for value in values:
        value=raw(value);digest.update(len(value).to_bytes(8,'big'));digest.update(value)
    return digest.hexdigest()

def canonical_stream(full):
    f=fields(full,[b'length',b'radix-tree-keys',b'radix-tree-nodes',b'last-generated-id',
        b'max-deleted-entry-id',b'entries-added',b'recorded-first-entry-id',b'entries',b'groups'])
    length=number(f[b'length'])
    number(f[b'radix-tree-keys']);number(f[b'radix-tree-nodes'])
    entries=f[b'entries']
    if not isinstance(entries,list) or len(entries)!=length or length>MAX_ENTRIES:fail('incomplete stream entries')
    entry_rows=[];ids=set()
    for row in entries:
        if not isinstance(row,list) or len(row)!=2:fail('malformed stream entry')
        ident=stream_id(row[0]);payload=row[1]
        if ident in ids or not isinstance(payload,list) or not payload or len(payload)%2:fail('duplicate ID or malformed payload')
        ids.add(ident)
        # Ordered raw field/value pairs retain duplicate field names; no dict collapse.
        entry_rows.append({'id':ident,'field_count':len(payload)//2,'payload_sha256':framed_hash(payload)})
    groups=[];observations=[];group_names=set()
    if not isinstance(f[b'groups'],list) or len(f[b'groups'])>MAX_GROUPS:fail('group bound')
    for group in f[b'groups']:
        g=fields(group,[b'name',b'last-delivered-id',b'entries-read',b'lag',b'pel-count',b'pending',b'consumers'])
        name=fingerprint(raw(g[b'name']))
        if name in group_names:fail('duplicate group')
        group_names.add(name);pending=[];pending_ids=set()
        if not isinstance(g[b'pending'],list) or len(g[b'pending'])!=number(g[b'pel-count']) or len(g[b'pending'])>MAX_ENTRIES:fail('incomplete group PEL')
        for row in g[b'pending']:
            if not isinstance(row,list) or len(row)!=4:fail('malformed group PEL')
            ident=stream_id(row[0])
            if ident in pending_ids:fail('duplicate pending ID')
            pending_ids.add(ident)
            pending.append({'id':ident,'consumer_sha256':fingerprint(raw(row[1])),
                'delivery_time_ms':number(row[2]),'delivery_count':number(row[3])})
        consumers=[];consumer_names=set();consumer_pel=[]
        if not isinstance(g[b'consumers'],list) or len(g[b'consumers'])>MAX_CONSUMERS:fail('consumer bound')
        for consumer in g[b'consumers']:
            c=fields(consumer,[b'name',b'seen-time',b'active-time',b'pel-count',b'pending'])
            cname=fingerprint(raw(c[b'name']))
            if cname in consumer_names:fail('duplicate consumer')
            consumer_names.add(cname);cp=[]
            if not isinstance(c[b'pending'],list) or len(c[b'pending'])!=number(c[b'pel-count']):fail('incomplete consumer PEL')
            for row in c[b'pending']:
                if not isinstance(row,list) or len(row)!=3:fail('malformed consumer PEL')
                p={'id':stream_id(row[0]),'consumer_sha256':cname,'delivery_time_ms':number(row[1]),'delivery_count':number(row[2])}
                cp.append(p);consumer_pel.append(p)
            consumers.append({'name_sha256':cname,'pending':sorted(cp,key=lambda p:p['id'])})
            observations.append({'group_sha256':name,'consumer_sha256':cname,
                'seen_time_ms':number(c[b'seen-time']), 'active_time_ms':number(c[b'active-time'],minimum=-1)})
        if sorted(consumer_pel,key=lambda p:p['id'])!=sorted(pending,key=lambda p:p['id']):fail('group/consumer PEL ownership inconsistent')
        groups.append({'name_sha256':name,'last_delivered_id':stream_id(g[b'last-delivered-id']),
            'entries_read':number(g[b'entries-read'],minimum=-1,nullable=True),
            'lag':number(g[b'lag'],minimum=-1,nullable=True),'pending':sorted(pending,key=lambda p:p['id']),
            'consumers':sorted(consumers,key=lambda c:c['name_sha256'])})
    stable={'length':length,'entries':entry_rows,'groups':sorted(groups,key=lambda g:g['name_sha256'])}
    for field in (b'last-generated-id',b'max-deleted-entry-id',b'recorded-first-entry-id'):stable[field.decode()]=stream_id(f[field])
    stable['entries-added']=number(f[b'entries-added'])
    return stable,sorted(observations,key=lambda c:(c['group_sha256'],c['consumer_sha256']))

def semantic_census(client):
    observed,rows=client.execute_command('EVAL_RO',READ,0,MAX_KEYS,MAX_KEY_BYTES,MAX_ENTRIES,MAX_GROUPS,MAX_CONSUMERS)
    result=[]
    for key,kind,dump,expires,full in rows:
        record={'key_sha256':fingerprint(raw(key)),'type':raw(kind).decode('ascii'),
            'expires_at_ms':number(expires,minimum=-1),'serialized_sha256':fingerprint(raw(dump)),
            'serialized_bytes':len(dump)}
        if kind==b'stream':record['stable'],record['activity_clocks']=canonical_stream(full)
        result.append(record)
    return {'schema':'redis-recovery-semantic-v1','observed_at_ms':number(observed),
            'keys':sorted(result,key=lambda k:k['key_sha256'])}

def _hash(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value):fail('invalid fingerprint')

def _proof_id(value):
    if not isinstance(value,str):fail('invalid proof ID')
    return stream_id(value.encode('ascii'))

def _pending(row):
    if not isinstance(row,dict) or set(row)!={'id','consumer_sha256','delivery_time_ms','delivery_count'}:fail('incomplete pending proof')
    _proof_id(row['id']);_hash(row['consumer_sha256']);number(row['delivery_time_ms']);number(row['delivery_count'])

def _validate_stream_proof(key):
    s=key['stable']
    required={'length','entries','groups','last-generated-id','max-deleted-entry-id','recorded-first-entry-id','entries-added'}
    if not isinstance(s,dict) or set(s)!=required:fail('incomplete stable stream proof')
    length=number(s['length']);number(s['entries-added'])
    for name in ('last-generated-id','max-deleted-entry-id','recorded-first-entry-id'):_proof_id(s[name])
    if not isinstance(s['entries'],list) or len(s['entries'])!=length or length>MAX_ENTRIES:fail('incomplete entry proof')
    ids=set()
    for entry in s['entries']:
        if not isinstance(entry,dict) or set(entry)!={'id','field_count','payload_sha256'}:fail('incomplete entry proof')
        _proof_id(entry['id']);number(entry['field_count'],minimum=1);_hash(entry['payload_sha256'])
        if entry['id'] in ids:fail('duplicate proof entry')
        ids.add(entry['id'])
    if not isinstance(s['groups'],list) or len(s['groups'])>MAX_GROUPS:fail('group proof bound')
    identities=set();group_names=set()
    for g in s['groups']:
        if not isinstance(g,dict) or set(g)!={'name_sha256','last_delivered_id','entries_read','lag','pending','consumers'}:fail('incomplete group proof')
        _hash(g['name_sha256']);_proof_id(g['last_delivered_id'])
        if g['name_sha256'] in group_names:fail('duplicate group proof')
        group_names.add(g['name_sha256']);number(g['entries_read'],minimum=-1,nullable=True);number(g['lag'],minimum=-1,nullable=True)
        if not isinstance(g['pending'],list) or len(g['pending'])>MAX_ENTRIES:fail('PEL proof bound')
        pending_ids=set()
        for row in g['pending']:
            _pending(row)
            if row['id'] in pending_ids:fail('duplicate PEL proof')
            pending_ids.add(row['id'])
        if not isinstance(g['consumers'],list) or len(g['consumers'])>MAX_CONSUMERS:fail('consumer proof bound')
        consumer_pel=[]
        for c in g['consumers']:
            if not isinstance(c,dict) or set(c)!={'name_sha256','pending'}:fail('incomplete consumer proof')
            _hash(c['name_sha256']);identity=(g['name_sha256'],c['name_sha256'])
            if identity in identities:fail('duplicate consumer proof')
            identities.add(identity)
            if not isinstance(c['pending'],list):fail('incomplete consumer PEL proof')
            for row in c['pending']:
                _pending(row)
                if row['consumer_sha256']!=c['name_sha256']:fail('consumer PEL owner differs')
                consumer_pel.append(row)
        if sorted(g['pending'],key=lambda p:p['id'])!=sorted(consumer_pel,key=lambda p:p['id']):fail('group/consumer proof differs')
    clocks=key['activity_clocks'];seen=set()
    if not isinstance(clocks,list):fail('activity proof missing')
    for c in clocks:
        if not isinstance(c,dict) or set(c)!={'group_sha256','consumer_sha256','seen_time_ms','active_time_ms'}:fail('activity proof incomplete')
        identity=(c['group_sha256'],c['consumer_sha256'])
        if identity in seen:fail('duplicate activity proof')
        seen.add(identity);number(c['seen_time_ms']);number(c['active_time_ms'],minimum=-1)
    if seen!=identities:fail('activity identity set differs')

def verify_semantic_recovery(expected,recovered,*,mode='rdb',recovery_window_ms=None):
    if mode not in ('rdb','aof'):fail('unknown recovery mode')
    if expected.get('schema')!='redis-recovery-semantic-v1' or recovered.get('schema')!=expected['schema']:fail('proof schema missing/mismatched')
    if mode=='aof':
        if not isinstance(recovery_window_ms,tuple) or len(recovery_window_ms)!=2:fail('AOF recovery window required')
        low,high=recovery_window_ms
        if type(low)!=int or type(high)!=int or low>high:fail('invalid AOF recovery window')
    keys_a=expected.get('keys');keys_b=recovered.get('keys')
    if not isinstance(keys_a,list) or not isinstance(keys_b,list) or len(keys_a)!=len(keys_b):fail('key set mismatch')
    for proof in (expected,recovered):
        number(proof.get('observed_at_ms'))
        names=set()
        for key in proof['keys']:
            required={'key_sha256','type','expires_at_ms','serialized_sha256','serialized_bytes'}
            if key.get('type')=='stream':required|={'stable','activity_clocks'}
            if set(key)!=required:fail('unknown or missing proof field')
            for field in ('key_sha256','serialized_sha256'):
                if not isinstance(key[field],str) or not re.fullmatch(r'[0-9a-f]{64}',key[field]):fail('invalid fingerprint')
            if key['key_sha256'] in names:fail('duplicate key proof')
            names.add(key['key_sha256']);number(key['expires_at_ms'],minimum=-1);number(key['serialized_bytes'])
            if key['type']=='stream':_validate_stream_proof(key)
    changes=[];clocks=[]
    for before,after in zip(keys_a,keys_b):
        if any(before.get(k)!=after.get(k) for k in ('key_sha256','type','expires_at_ms')):fail('key identity/type/expiry differs')
        if before['type']!='stream':
            if before!=after:fail('nonstream serialized evidence differs')
            continue
        if 'stable' not in before or 'stable' not in after or before['stable']!=after['stable']:fail('stream evidence/PEL differs')
        a=before.get('activity_clocks');b=after.get('activity_clocks')
        if not isinstance(a,list) or not isinstance(b,list) or len(a)!=len(b):fail('consumer activity identity missing')
        for old,new in zip(a,b):
            if any(old.get(k)!=new.get(k) for k in ('group_sha256','consumer_sha256')):fail('consumer activity identity differs')
            for field in ('seen_time_ms','active_time_ms'):
                value=number(new.get(field),minimum=-1 if field=='active_time_ms' else 0)
                if value!=old.get(field):
                    if mode!='aof' or not low<=value<=high:fail('consumer clock change outside declared replay window')
                    clocks.append({'key_sha256':before['key_sha256'],'consumer_sha256':new['consumer_sha256'],
                                   'field':field,'before':old[field],'after':value})
        if before['serialized_sha256']!=after['serialized_sha256'] or before['serialized_bytes']!=after['serialized_bytes']:
            changes.append(before['key_sha256'])
    return {'status':'MATCH','mode':mode,'representation_changes':changes,'consumer_clock_changes':clocks}

def recovery_window(client,proof):
    """Bound Redis's own startup epoch using its uptime, not an assumed host clock.

    Uptime seconds are truncated: the lower bound includes the missing fraction.
    The upper bound is this Redis census's observed clock. Clock contradictions
    fail the gate; they are not silently corrected.
    """
    info=client.info('server')
    now=number(info.get('server_time_usec'))//1000
    uptime=number(info.get('uptime_in_seconds'))
    lower=now-(uptime+1)*1000
    upper=number(proof.get('observed_at_ms'))
    if lower<0 or lower>upper:fail('Redis recovery clock contradiction')
    return lower,upper
