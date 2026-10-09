import copy
import pytest
from scripts import redis_stream_integrity as gate

def full():
    consumer=[b'name',b'alice',b'seen-time',100,b'active-time',100,b'pel-count',1,
        b'pending',[[b'1-0',90,1]]]
    group=[b'name',b'group',b'last-delivered-id',b'1-0',b'entries-read',1,b'lag',0,
        b'pel-count',1,b'pending',[[b'1-0',b'alice',90,1]],b'consumers',[consumer]]
    return [b'length',1,b'radix-tree-keys',1,b'radix-tree-nodes',2,
        b'last-generated-id',b'1-0',b'max-deleted-entry-id',b'0-0',b'entries-added',1,
        b'recorded-first-entry-id',b'1-0',b'entries',[[b'1-0',[b'field',b'value',b'field',b'\x00\xff']]],b'groups',[group]]

def proof(value=None,sha='a'*64):
    stable,clocks=gate.canonical_stream(full() if value is None else value)
    return {'schema':'redis-recovery-semantic-v1','observed_at_ms':200,
        'keys':[{'key_sha256':'b'*64,'type':'stream','expires_at_ms':-1,
          'serialized_sha256':sha,'serialized_bytes':201,'stable':stable,'activity_clocks':clocks}]}

def test_exact_rdb_evidence_and_clock_recovery_passes():
    expected=proof();assert gate.verify_semantic_recovery(expected,copy.deepcopy(expected))['status']=='MATCH'

def test_declared_aof_clock_reset_is_recorded_not_hidden():
    expected=proof();recovered=proof(sha='c'*64)
    for c in recovered['keys'][0]['activity_clocks']:c['seen_time_ms']=c['active_time_ms']=190
    result=gate.verify_semantic_recovery(expected,recovered,mode='aof',recovery_window_ms=(180,200))
    assert len(result['consumer_clock_changes'])==2
    assert result['consumer_clock_changes'][0]['before']==100
    assert result['consumer_clock_changes'][0]['after']==190
    assert result['representation_changes']==['b'*64]

def test_clock_change_not_permitted_for_rdb():
    a=proof();b=proof();b['keys'][0]['activity_clocks'][0]['seen_time_ms']=190
    with pytest.raises(ValueError,match='clock'):gate.verify_semantic_recovery(a,b)

def test_aof_window_required():
    with pytest.raises(ValueError,match='window'):gate.verify_semantic_recovery(proof(),proof(),mode='aof')

def test_reset_outside_replay_window_fails():
    a=proof();b=proof();b['keys'][0]['activity_clocks'][0]['seen_time_ms']=300
    with pytest.raises(ValueError,match='clock'):gate.verify_semantic_recovery(a,b,mode='aof',recovery_window_ms=(180,200))

@pytest.mark.parametrize('corrupt',['payload','omit','id','field_order','ownership','delivery_count','delivery_time','cursor','consumer','expiry'])
def test_evidence_corruption_never_hidden_by_clock_variance(corrupt):
    expected=proof();recovered=copy.deepcopy(expected);k=recovered['keys'][0];s=k['stable']
    if corrupt=='payload':s['entries'][0]['payload_sha256']='f'*64
    elif corrupt=='omit':s['entries']=[]
    elif corrupt=='id':s['entries'][0]['id']='2-0'
    elif corrupt=='field_order':s['entries'][0]['payload_sha256']=gate.framed_hash([b'field',b'\x00\xff',b'field',b'value'])
    elif corrupt=='ownership':s['groups'][0]['pending'][0]['consumer_sha256']='f'*64
    elif corrupt=='delivery_count':s['groups'][0]['pending'][0]['delivery_count']=2
    elif corrupt=='delivery_time':s['groups'][0]['pending'][0]['delivery_time_ms']=91
    elif corrupt=='cursor':s['groups'][0]['last_delivered_id']='2-0'
    elif corrupt=='consumer':s['groups'][0]['consumers']=[]
    elif corrupt=='expiry':k['expires_at_ms']=400
    k['activity_clocks'][0]['seen_time_ms']=190
    with pytest.raises(ValueError):gate.verify_semantic_recovery(expected,recovered,mode='aof',recovery_window_ms=(180,200))

def test_duplicate_payload_field_names_are_retained_and_order_matters():
    a=proof();value=full();entries=value[value.index(b'entries')+1]
    entries[0][1]=[b'field',b'\x00\xff',b'field',b'value']
    b=proof(value)
    assert a['keys'][0]['stable']['entries'][0]['field_count']==2
    with pytest.raises(ValueError):gate.verify_semantic_recovery(a,b)

def test_length_prefix_avoids_ambiguous_payload_hashes():
    assert gate.framed_hash([b'ab',b'c'])!=gate.framed_hash([b'a',b'bc'])

def test_incomplete_full_response_fails():
    value=full();value[value.index(b'entries')+1]=[]
    with pytest.raises(ValueError,match='incomplete'):gate.canonical_stream(value)

def test_inconsistent_consumer_ownership_fails():
    value=full();g=value[value.index(b'groups')+1][0]
    g[g.index(b'pending')+1][0][1]=b'bob'
    with pytest.raises(ValueError,match='ownership'):gate.canonical_stream(value)

def test_unknown_metadata_is_not_silently_ignored():
    with pytest.raises(ValueError,match='unknown'):gate.canonical_stream(full()+[b'new-field',123])

def test_nonstream_raw_fingerprint_remains_strict():
    a=proof();k=a['keys'][0];k['type']='string';del k['stable'];del k['activity_clocks']
    b=copy.deepcopy(a);b['keys'][0]['serialized_sha256']='c'*64
    with pytest.raises(ValueError,match='nonstream'):gate.verify_semantic_recovery(a,b)

def test_disconnected_census_does_not_fabricate_empty_success():
    class Offline:
        def execute_command(self,*a):raise ConnectionError('disconnected')
    with pytest.raises(ConnectionError):gate.semantic_census(Offline())

def test_recovery_window_uses_redis_clock_domain():
    class Client:
        def info(self,name):return {'server_time_usec':10_500_000,'uptime_in_seconds':1}
    assert gate.recovery_window(Client(),{'observed_at_ms':10_450})==(8500,10450)

def test_missing_or_duplicate_key_proof_fails_closed():
    a=proof();b=copy.deepcopy(a);b['keys'][0]['key_sha256']='invalid'
    with pytest.raises(ValueError,match='fingerprint'):gate.verify_semantic_recovery(a,b)

@pytest.mark.parametrize('missing',['stable','entries','pending','activity'])
def test_identical_incomplete_proofs_do_not_pass(missing):
    a=proof();k=a['keys'][0]
    if missing=='stable':k['stable']={}
    elif missing=='entries':k['stable']['entries']=[]
    elif missing=='pending':k['stable']['groups'][0]['consumers'][0]['pending']=[]
    else:k['activity_clocks']=[]
    with pytest.raises(ValueError):gate.verify_semantic_recovery(a,copy.deepcopy(a))
