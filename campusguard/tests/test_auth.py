from concurrent.futures import ThreadPoolExecutor
import pytest
from app.auth import PASSWORDS
from app.domain import token_hash

pytestmark = pytest.mark.integration


def login(client, username='owner', password='synthetic-password', browser=False):
    return client.post('/api/v1/auth/login' if browser else '/api/v1/auth/token',
                       json={'username':username,'password':password})


def add(client, owner_headers, username, role='viewer'):
    response = client.post('/api/v1/admin/users',headers=owner_headers,
                           json={'username':username,'password':'synthetic-password','role':role})
    assert response.status_code == 201, response.text
    return response.json()['id']


def bearer(response):
    assert response.status_code == 200, response.text
    return {'Authorization':'Bearer '+response.json()['access_token']}


def test_cookie_session_csrf_and_logout(system):
    c,p,h,a = system
    response = login(c,browser=True)
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    assert 'access_token' not in response.json()
    assert c.get('/api/v1/auth/me').json()['username']=='owner'
    assert c.post('/api/v1/auth/logout').status_code==403
    csrf=response.json()['csrf_token']
    assert c.post('/api/v1/auth/logout',headers={'X-CSRF-Token':csrf,'Origin':'https://evil.invalid'}).status_code==403
    assert c.post('/api/v1/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert c.get('/api/v1/auth/me').status_code==401
    # Only this cookie session is revoked; the fixture's CLI session remains valid.
    assert c.get('/api/v1/auth/me',headers=a).status_code==200


def test_origin_login_and_legacy_token_rejected(system):
    c,p,h,a=system
    assert c.post('/api/v1/auth/login',headers={'Origin':'https://evil.invalid'},json={'username':'owner','password':'synthetic-password'}).status_code==403
    assert c.get('/api/v1/admin/students',headers={'x-admin-token':'a'*40}).status_code==401
    assert login(c,'owner','wrong').status_code==401
    assert login(c,'unknown','wrong').status_code==401


@pytest.mark.parametrize('role,can_enroll,can_terminals', [('viewer',False,False),('operator',True,False),('owner',True,True)])
def test_permissions_and_phone_redaction(system,monkeypatch,role,can_enroll,can_terminals):
    c,p,h,a=system
    add(c,a,'member',role)
    member=bearer(login(c,'member'))
    assert c.get('/api/v1/admin/dashboard-stats',headers=member).status_code==200
    phone=c.get('/api/v1/admin/students',headers=member).json()[0]['phone_number']
    assert phone is None if role=='viewer' else phone==''
    monkeypatch.setattr('app.main.extract_embedding',lambda _:[.2]*128)
    enrollment=c.post('/api/v1/admin/register-student',headers=member,data={'student_id':'S002','full_name':'Synthetic Two','consent':'true'},files={'file':('x.jpg',b'x','image/jpeg')})
    assert enrollment.status_code==(200 if can_enroll else 403)
    assert c.post('/api/v1/admin/register-terminal',headers=member,data={'terminal_uuid':'second','api_secret_token':'z'*40,'location_name':'Test','direction':'IN'}).status_code==(200 if can_terminals else 403)
    assert c.get('/api/v1/admin/users',headers=member).status_code==(200 if role=='owner' else 403)
    assert c.get('/api/v1/admin/audit',headers=member).status_code==(200 if role=='owner' else 403)


def test_role_change_and_disable_revoke_existing_sessions(system):
    c,p,h,a=system
    ident=add(c,a,'member','operator')
    old=bearer(login(c,'member'))
    assert c.patch(f'/api/v1/admin/users/{ident}',headers=a,json={'role':'viewer'}).status_code==200
    assert c.get('/api/v1/admin/students',headers=old).status_code==401
    new=bearer(login(c,'member'))
    assert c.delete('/api/v1/admin/students/1',headers=new).status_code==403
    assert c.patch(f'/api/v1/admin/users/{ident}',headers=a,json={'active':False}).status_code==200
    assert c.get('/api/v1/auth/me',headers=new).status_code==401
    assert login(c,'member').status_code==401


def test_password_change_and_owner_reset(system):
    c,p,h,a=system
    ident=add(c,a,'member','operator')
    old=bearer(login(c,'member'))
    assert c.post('/api/v1/auth/password',headers=old,json={'current_password':'wrong','new_password':'new-synthetic-password'}).status_code==401
    assert c.post('/api/v1/auth/password',headers=old,json={'current_password':'synthetic-password','new_password':'new-synthetic-password'}).status_code==200
    assert c.get('/api/v1/auth/me',headers=old).status_code==401
    assert login(c,'member').status_code==401
    new=bearer(login(c,'member','new-synthetic-password'))
    assert c.post(f'/api/v1/admin/users/{ident}/reset-password',headers=a,json={'new_password':'reset-synthetic-password'}).status_code==200
    assert c.get('/api/v1/auth/me',headers=new).status_code==401
    assert login(c,'member','reset-synthetic-password').status_code==200


def test_expiry_and_password_hash_storage(system):
    c,p,h,a=system
    with p.connection() as conn:
        row=conn.execute("SELECT password_hash FROM admin_users WHERE username='owner'").fetchone()
        assert row['password_hash'].startswith('$argon2id$')
        conn.execute('UPDATE admin_sessions SET expires_at=now()-interval \'1 second\'')
    assert c.get('/api/v1/auth/me',headers=a).status_code==401


def test_last_owner_and_concurrent_demotion(system):
    c,p,h,a=system
    owner_id=c.get('/api/v1/auth/me',headers=a).json()['id']
    assert c.patch(f'/api/v1/admin/users/{owner_id}',headers=a,json={'active':False}).status_code==409
    second_id=add(c,a,'second','owner')
    second=bearer(login(c,'second'))
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures=[ex.submit(c.patch,f'/api/v1/admin/users/{ident}',headers=headers,json={'role':'viewer'})
                 for ident,headers in [(owner_id,a),(second_id,second)]]
        responses=[f.result() for f in futures]
    assert sorted(r.status_code for r in responses)==[200,409]
    with p.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM admin_users WHERE active AND role='owner'").fetchone()['n']==1


def test_rate_limit_survives_failed_login_transactions(system):
    c,p,h,a=system
    # Fixture login is attempt 1; nine wrong passwords count even though their user transaction rolls back.
    for _ in range(9):
        assert login(c,'owner','wrong').status_code==401
    response=login(c)
    assert response.status_code==429 and int(response.headers['retry-after'])>0
    with p.connection() as conn:
        assert conn.execute('SELECT max(attempts) AS n FROM auth_rate_limits').fetchone()['n']==11


def test_validation_uniqueness_and_attributed_audit(system):
    c,p,h,a=system
    ident=add(c,a,'Mixed.Case')
    assert login(c,'MIXED.CASE').status_code==200
    assert c.post('/api/v1/admin/users',headers=a,json={'username':'mixed.case','password':'synthetic-password','role':'viewer'}).status_code==409
    assert c.post('/api/v1/admin/users',headers=a,json={'username':'weak','password':'short','role':'viewer'}).status_code==422
    assert c.post('/api/v1/admin/users',headers=a,json={'username':'invalid','password':'synthetic-password','role':'root'}).status_code==422
    assert c.delete('/api/v1/admin/students/1',headers=a).status_code==200
    rows=c.get('/api/v1/admin/audit',headers=a).json()
    assert any(r['action']=='student.deleted' and r['actor_username']=='owner' and r['actor_id'] for r in rows)
    assert all('password' not in r and 'token_hash' not in r for r in c.get('/api/v1/admin/users',headers=a).json())


def test_user_mutation_rolls_back_if_audit_cannot_be_written(system):
    c,p,h,a=system
    with p.connection() as conn:
        conn.execute("ALTER TABLE audit_events ADD CONSTRAINT test_audit_failure CHECK(action != 'user.created')")
    result=c.post('/api/v1/admin/users',headers=a,json={'username':'rollback','password':'synthetic-password','role':'viewer'})
    assert result.status_code==503
    with p.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM admin_users WHERE username='rollback'").fetchone()['n']==0
