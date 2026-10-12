"""Inactive trusted-controller join of native participant and Redis writer proofs.

No process or container operations. Call under the existing lifecycle lock. Native
participant channels must already be authenticated; no writer RPC exposes this seam.
"""
import hashlib
import json
import re
import math
import time

from scripts.redis_production_adapters import read_records
from scripts.redis_stream_integrity import verify_semantic_recovery
from stinky_core.transport.redis_accounting import AccountingError


def certify_participants(broker, *, request_id, acknowledgements, journals,
                         inspect_connections, census, audit, timeout=10):
    """Fail closed unless every registered native writer has a durable phase ACK.

    Not a complete service inventory, snapshot or lifecycle certificate. The normal
    production legacy workload cannot satisfy this protected-writer boundary.
    """
    try:
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=60:
            raise AccountingError('Bounded controller deadline required')
        deadline=time.monotonic()+timeout
        def check_deadline():
            if time.monotonic()>=deadline:raise AccountingError('Cooperative boundary deadline exceeded')
        if not isinstance(request_id,str) or not re.fullmatch('[0-9a-f]{32}',request_id):
            raise AccountingError('Fresh controller request identity required')
        if (not isinstance(acknowledgements,list) or not 1<=len(acknowledgements)<=128 or
            len(acknowledgements)!=len(broker.manifest)):
            raise AccountingError('Complete participant acknowledgement set required')
        with broker.lock:
            seen=set();heads={}
            for ack in acknowledgements:
                fields={'phase','owner','request_id','manifest_sha256','journal_head','acknowledged','scope'}
                if not isinstance(ack,dict) or set(ack)!=fields:
                    raise AccountingError('Malformed participant acknowledgement')
                pid=ack['owner']['pid']
                if pid in seen or broker.owner(pid)!=ack['owner']:
                    raise AccountingError('Unknown, duplicate or replaced participant')
                seen.add(pid)
                prefix=f"{pid}-{ack['owner']['creation_ticks']}-"
                roles=sorted(writer[len(prefix):] for writer in broker.ledger.writers if writer.startswith(prefix))
                body={'owner':ack['owner'],'generation':broker.generation,
                      'server_epoch':broker.server_epoch,'roles':roles}
                digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if (not roles or ack['phase']!='QUIESCED' or ack['request_id']!=request_id or
                    ack['manifest_sha256']!=digest or
                    type(ack['acknowledged']) is not int or ack['acknowledged']<0 or
                    ack['scope']!='PARTICIPANT_ONLY_NOT_FINAL_RECOVERY_BOUNDARY'):
                    raise AccountingError('Participant phase or route contradicts controller')
                rows=read_records(journals[pid],expected_head=ack['journal_head'],max_bytes=16384)
                expected=[{'stage':'COOPERATIVE_PHASE','phase':phase,'request_id':request_id,
                           'manifest_sha256':digest} for phase in ('FENCING','DRAINING','QUIESCED')]
                if rows!=expected:raise AccountingError('Participant audit does not prove shutdown sequence')
                heads[pid]=ack['journal_head']
                check_deadline()
            if seen!=set(broker.manifest):raise AccountingError('Native writer coverage incomplete')
            result=broker.drain_registered(inspect_connections,timeout=deadline-time.monotonic())
            if any(ack['acknowledged']!=result['acknowledged'] for ack in acknowledgements):
                raise AccountingError('Participant accounting boundary differs')
            revoked=broker.credentials.revoke_all()
            if revoked!={'status':'REVOKED','verified':True,'durable':True}:
                raise AccountingError('Durable writer revocation unavailable; HOLD')
            if broker.credentials.verify_principals() is not True:
                raise AccountingError('Server-side writer exclusion unavailable')
            before=census();after=census()
            verify_semantic_recovery(before,after,mode='rdb')
            check_deadline()
            for pid in seen:broker.owner(pid)
            if broker.held or not broker.fenced or broker.ledger.settled()!=result['acknowledged']:
                raise AccountingError('Final writer boundary changed')
            row={'stage':'COOPERATIVE_WRITER_BOUNDARY','request_id':request_id,
                 'participant_heads':heads,'accounting_head':broker.ledger.journal.previous,
                 'acknowledged':result['acknowledged']}
            audit.persist(row)
            # A slow audit may expose controller loss/identity replacement. Never
            # release a verified result without one more native/authority check.
            for pid in seen:broker.owner(pid)
            if broker.held or not broker.fenced or broker.credentials.verify_principals() is not True:
                raise AccountingError('Authority changed during boundary audit')
            observed=inspect_connections()
            expected={row['client_id'] for row in broker.ledger.bindings.values() if row['active']}
            if (not isinstance(observed,list) or len(observed)!=len(set(observed)) or
                set(observed)!=expected):raise AccountingError('Writer inventory changed during boundary audit')
            verify_semantic_recovery(after,census(),mode='rdb')
            check_deadline()
            return {**row,'phase':'WRITERS_FENCED_DRAINED','journal_head':audit.previous,
                    'scope':'REGISTERED_WRITERS_ONLY_NOT_FULL_LIFECYCLE'}
    except BaseException:
        try:broker.hold()
        except BaseException:broker.held=broker.fenced=True
        raise
