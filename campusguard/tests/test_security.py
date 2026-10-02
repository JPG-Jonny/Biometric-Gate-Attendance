import io
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from app.biometrics import extract_embedding
from app.config import Settings
from app.main import create_app


def client():
    settings=Settings(database_url='postgresql://unused',encryption_key=Fernet.generate_key().decode())
    # No lifespan entered and no DB call needed for these early rejection paths.
    return TestClient(create_app(settings,pool=object()))

def test_missing_admin_token_and_security_headers():
    with_client=client()
    result=with_client.get('/api/v1/admin/students')
    assert result.status_code==401
    assert result.headers['cache-control']=='no-store'
    assert result.headers['x-content-type-options']=='nosniff'
    assert 'access-control-allow-origin' not in result.headers

def test_request_limits_apply_before_parsing():
    c=client()
    assert c.post('/api/v1/gate/verify-face',content=b'x'*20001).status_code==413
    assert c.post('/api/v1/admin/register-student',content=b'x'*(5*1024*1024+1)).status_code==413

@pytest.mark.parametrize('data,code',[(b'',413),(b'not an image',400),(b'x'*(4*1024*1024+1),413)])
def test_invalid_images(data,code):
    with pytest.raises(HTTPException) as exc: extract_embedding(data)
    assert exc.value.status_code==code

def test_pixel_limit():
    b=io.BytesIO();Image.new('RGB',(2100,2100)).save(b,format='PNG')
    with pytest.raises(HTTPException) as exc: extract_embedding(b.getvalue())
    assert exc.value.status_code==413

def test_configuration_fails_without_secrets():
    with pytest.raises(ValueError): Settings(database_url='',encryption_key='')
