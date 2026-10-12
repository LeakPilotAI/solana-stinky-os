import json
import pytest
from scripts.redis_writer_broker import PipeProxy,pack
from stinky_core.transport.redis_accounting import reply_bytes,AccountingError

def test_production_sized_group_reply_fits_existing_bound_without_duplicate_bytes():
    reply=[[b'proof',[[f'{n+1}-0'.encode(),{b'data':b'x'*1100}] for n in range(500)]]]
    canonical=reply_bytes(reply)
    old=json.dumps(pack({'sequence':1,'method':'complete_command','args':[1,reply,canonical,'fixture']})).encode()
    new=json.dumps(pack({'sequence':1,'method':'complete_reply','args':[1,reply,'fixture']})).encode()
    assert len(old)>1024*1024 and len(new)<1024*1024
    proxy=PipeProxy('\\\\.\\pipe\\genesis-unit',b'x'*32,[],server_identity=(1,10))
    calls=[];proxy.call=lambda *args:calls.append(args)
    proxy.complete_command(1,reply,canonical,'fixture')
    assert calls==[('complete_reply',1,reply,'fixture')]
    # The server reconstructs exactly the canonical digest input, not a receipt
    # count or opaque caller-provided hash substituting for the original reply.
    assert reply_bytes(calls[0][2])==canonical

def test_mismatched_local_serialization_cannot_send_a_completion():
    proxy=PipeProxy('\\\\.\\pipe\\genesis-unit',b'x'*32,[],server_identity=(1,10))
    calls=[];proxy.call=lambda *args:calls.append(args)
    with pytest.raises(AccountingError,match='serialization'):
        proxy.complete_command(1,1,b'wrong','fixture')
    assert proxy.failed and not calls
