from datetime import datetime, date, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.domain import Scan, day_bounds, nearest_match, status_for, fingerprint

S=SimpleNamespace(timezone='Asia/Kolkata',class_start='09:00',class_end='16:00')
@pytest.mark.parametrize('direction,clock,expected',[
 ('IN','08:59:59','In-Time Entry'),('IN','09:00:00','In-Time Entry'),
 ('IN','09:00:01','Late Entry'),('IN','16:00:00','After Scheduled Hours'),
 ('OUT','15:59:59','Early Exit'),('OUT','16:00:00','Exit'),('OUT','23:00:00','Exit')])
def test_schedule(direction,clock,expected):
    dt=datetime.fromisoformat('2026-09-25T'+clock+'+05:30')
    assert status_for(direction,dt.astimezone(timezone.utc),S)==expected

@pytest.mark.parametrize('bad',[[0.0]*127,[float('nan')]*128,[float('inf')]*128,[20.0]*128])
def test_embedding_validation(bad):
    with pytest.raises(ValidationError):
        Scan(event_id=uuid4(),occurred_at=datetime.now(timezone.utc),direction='IN',embedding=bad)

def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        Scan(event_id=uuid4(),occurred_at=datetime.now(),direction='IN',embedding=[0.0]*128)

def test_timezone_day_bounds():
    start,end=day_bounds(date(2026,9,25),'Asia/Kolkata')
    assert start.astimezone(timezone.utc).isoformat()=='2026-09-24T18:30:00+00:00'
    assert (end-start).total_seconds()==86400

def test_ambiguous_match_and_multiple_templates():
    v=[0.0]*128
    assert nearest_match(v,[(1,v),(2,v)],.5,.05) is None
    assert nearest_match(v,[(1,v),(1,v)],.5,.05)==1
    assert nearest_match(v,[(1,[1.0]*128)],.5,.05) is None
    assert nearest_match(v,[],.5,.05) is None

def test_fingerprint_same_instant_and_changed_payload():
    scan=Scan(event_id=uuid4(),occurred_at='2026-09-25T09:00:00+05:30',direction='IN',embedding=[0.0]*128)
    same=Scan(**{**scan.model_dump(),'occurred_at':'2026-09-25T03:30:00Z'})
    assert fingerprint(scan,'key')==fingerprint(same,'key')
    assert fingerprint(scan,'key')!=fingerprint(scan.model_copy(update={'direction':'OUT'}),'key')
