import logging
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from cryptography.fernet import Fernet
from app.monitoring import JsonFormatter


def test_metrics_fail_closed_and_production_configuration():
    s=Settings(database_url='postgresql://unused',encryption_key=Fernet.generate_key().decode())
    c=TestClient(create_app(s,pool=object()))
    assert c.get('/metrics').status_code==401
    assert c.get('/health/live').headers['x-request-id']
    with pytest.raises(ValueError):
        Settings(database_url=s.database_url,encryption_key=s.encryption_key,environment='production')


@pytest.mark.integration
def test_authenticated_metrics_and_bounded_labels(system):
    c,p,h,a=system
    s=Settings(database_url='unused',encryption_key=Fernet.generate_key().decode(),metrics_token='m'*40)
    with TestClient(create_app(s,p)) as monitored:
        assert monitored.get('/metrics',headers=a).status_code==401
        for ident in ['1','2','3']:
            monitored.delete('/api/v1/admin/students/'+ident,headers={})
        body=monitored.get('/metrics',headers={'Authorization':'Bearer '+'m'*40}).text
        assert 'campusguard_database_ready 1.0' in body
        assert 'route="/api/v1/admin/students/{internal_id}"' in body
        assert 'synthetic-password' not in body and 'student_id=' not in body
        assert 'route="/api/v1/admin/students/1"' not in body


def test_structured_log_fields():
    record=logging.LogRecord('campusguard',logging.INFO,'',1,'request',(),None)
    record.request_id='request123';record.route='/api/v1/admin/students/{internal_id}'
    text=JsonFormatter().format(record)
    import json
    data=json.loads(text)
    assert data['request_id']=='request123' and data['route'].endswith('{internal_id}')


@pytest.mark.integration
def test_production_secure_cookie_and_disabled_documentation(system):
    c,p,h,a=system
    s=Settings(database_url='unused',encryption_key=Fernet.generate_key().decode(),metrics_token='m'*40,
               public_origin='https://campusguard.example',environment='production')
    with TestClient(create_app(s,p),base_url='https://campusguard.example') as production:
        login=production.post('/api/v1/auth/login',json={'username':'owner','password':'synthetic-password'})
        assert login.status_code==200 and 'Secure' in login.headers['set-cookie']
        assert production.get('/api/v1/auth/me').status_code==200
        assert production.get('/docs').status_code==404
        assert production.get('/openapi.json').status_code==404
        assert production.post('/api/v1/auth/logout',headers={'X-CSRF-Token':'wrong'}).status_code==403
