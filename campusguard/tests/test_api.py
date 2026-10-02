from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from psycopg import sql

pytestmark=pytest.mark.integration


def scan(**changes):
    return {**dict(event_id=str(uuid4()),occurred_at=datetime.now(timezone.utc).isoformat(),direction='IN',embedding=[0.0]*128),**changes}

def post(client,headers,payload): return client.post('/api/v1/gate/verify-face',headers=headers,json=payload)

def count(pool,table):
    with pool.connection() as c: return c.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']

def test_auth_and_static(system):
    c,p,h,a=system
    assert c.get('/api/v1/admin/students').status_code==401
    assert post(c,{},scan()).status_code==401
    assert c.get('/').status_code==200
    assert 'default-src' in c.get('/').headers['content-security-policy']
    assert c.get('/api/v1/admin/students',headers=a).json()[0]['student_id']=='S001'

def test_idempotency_and_conflict(system):
    c,p,h,a=system;s=scan()
    first=post(c,h,s);second=post(c,h,s)
    assert first.status_code==200 and first.json()['success']
    assert first.json()==second.json()
    assert count(p,'attendance_logs')==1
    assert post(c,h,{**s,'embedding':[.01]*128}).status_code==409

def test_concurrent_distinct_scans_only_one_event(system):
    c,p,h,a=system;s=scan();payloads=[{**s,'event_id':str(uuid4())} for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as ex: results=list(ex.map(lambda v:post(c,h,v),payloads))
    assert all(r.status_code==200 for r in results)
    assert sum(r.json()['success'] for r in results)==1
    assert count(p,'attendance_logs')==1
    assert count(p,'scan_receipts')==8

def test_concurrent_retries_same_response(system):
    c,p,h,a=system;s=scan()
    with ThreadPoolExecutor(max_workers=8) as ex: results=list(ex.map(lambda _:post(c,h,s),range(8)))
    assert all(r.status_code==200 and r.json()==results[0].json() for r in results)
    assert count(p,'attendance_logs')==1

def test_time_direction_validation_and_logs(system):
    c,p,h,a=system
    assert post(c,h,scan(direction='OUT')).status_code==409
    assert post(c,h,scan(occurred_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())).status_code==422
    assert post(c,h,scan(occurred_at=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat())).status_code==422
    assert post(c,h,scan(embedding=[0.0]*127)).status_code==422
    assert post(c,h,scan()).json()['success']
    log=c.get('/api/v1/admin/attendance/logs',headers=a).json()[0]
    assert log['student_id']=='S001'
    assert c.get('/api/v1/admin/attendance/logs?date=bad',headers=a).status_code==422
    assert c.get('/api/v1/admin/students?limit=1000',headers=a).status_code==422

def test_out_of_order_review_and_delete(system):
    c,p,h,a=system
    assert post(c,h,scan()).json()['success']
    older=scan(occurred_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    assert post(c,h,older).json()['review_required']
    assert c.delete('/api/v1/admin/students/1',headers=a).status_code==200
    assert count(p,'student_faces')==0 and count(p,'attendance_logs')==0
    assert post(c,h,older).json()['success'] # prior receipt survives; no duplicate write
    assert count(p,'attendance_logs')==0
    assert c.delete('/api/v1/admin/students/1',headers=a).status_code==404

def test_enrollment_rollback_on_face_insert_failure(system,monkeypatch):
    c,p,h,a=system
    monkeypatch.setattr('app.main.extract_embedding',lambda _: [0.0]*128)
    with p.connection() as conn:
        conn.execute("ALTER TABLE student_faces ADD CONSTRAINT test_fail CHECK(student_id=1)")
    response=c.post('/api/v1/admin/register-student',headers=a,data={'student_id':'S002','full_name':'Example','consent':'true'},files={'file':('x.jpg',b'x','image/jpeg')})
    assert response.status_code==503
    assert count(p,'students')==1

def test_registration_consent_duplicate_and_revocation(system,monkeypatch):
    c,p,h,a=system
    monkeypatch.setattr('app.main.extract_embedding',lambda _:[.2]*128)
    data={'student_id':'S002','full_name':'Example','consent':'true'};files={'file':('x.jpg',b'x','image/jpeg')}
    assert c.post('/api/v1/admin/register-student',headers=a,data={**data,'consent':'false'},files=files).status_code==422
    assert c.post('/api/v1/admin/register-student',headers=a,data=data,files=files).status_code==200
    assert c.post('/api/v1/admin/register-student',headers=a,data=data,files=files).status_code==409
    assert c.delete('/api/v1/admin/terminals/gate',headers=a).status_code==200
    assert post(c,h,scan()).status_code==401
