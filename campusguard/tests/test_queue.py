import json
from datetime import datetime, timezone
from uuid import uuid4
import pytest
import requests
from cryptography.fernet import Fernet
from clients.offline_sync import Queue

class Reply:
    def __init__(self,status,data=None): self.status_code=status;self.data=data
    def json(self): return self.data
class Session:
    def __init__(self,response): self.response=response;self.payloads=[]
    def post(self,*args,**kwargs):
        self.payloads.append(kwargs['json'])
        if isinstance(self.response,Exception): raise self.response
        return self.response

def payload():
    return dict(event_id=str(uuid4()),occurred_at=datetime.now(timezone.utc).isoformat(),direction='IN',embedding=[.123]*128)

def test_encrypted_persistent_retry_then_ack(tmp_path):
    path=tmp_path/'queue.sqlite3';key=Fernet.generate_key().decode();p=payload()
    q=Queue(path,key,'gate');q.enqueue(p)
    assert b'0.123' not in path.read_bytes()
    q=Queue(path,key,'gate')
    lost=Session(requests.Timeout());q.flush_once('http://localhost','token',lost)
    assert q.counts()=={'pending':1}
    with q.connection() as c: c.execute('UPDATE pending SET next_attempt=0')
    ok=Session(Reply(200,{'success':True,'event_id':p['event_id'],'status':'In-Time Entry'}))
    q.flush_once('http://localhost','token',ok)
    assert ok.payloads[0]==lost.payloads[0]==p
    assert q.counts()=={}

@pytest.mark.parametrize('code,expected',[(422,'dead'),(409,'dead'),(429,'pending'),(503,'pending'),(401,'pending')])
def test_failures_preserve_or_quarantine(tmp_path,code,expected):
    q=Queue(tmp_path/'q',Fernet.generate_key().decode(),'gate');q.enqueue(payload())
    q.flush_once('http://localhost','token',Session(Reply(code)))
    assert q.counts()=={expected:1}

def test_wrong_identity_and_id_collision(tmp_path):
    key=Fernet.generate_key().decode();q=Queue(tmp_path/'q',key,'a');p=payload();q.enqueue(p);q.enqueue(p)
    assert q.counts()=={'pending':1}
    with pytest.raises(ValueError): q.enqueue({**p,'direction':'OUT'})
    with pytest.raises(ValueError): Queue(tmp_path/'q',key,'b')

def test_bad_ack_is_not_deleted(tmp_path):
    q=Queue(tmp_path/'q',Fernet.generate_key().decode(),'gate');q.enqueue(payload())
    q.flush_once('http://localhost','token',Session(Reply(200,{'success':True,'event_id':'wrong'})))
    assert q.counts()=={'pending':1}
