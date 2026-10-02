import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app.config import Settings
from app.domain import token_hash
from app.main import create_app
from app.auth import PASSWORDS

@pytest.fixture
def system():
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('Set TEST_DATABASE_URL to run real PostgreSQL integration tests')
    schema='test_'+uuid4().hex
    with psycopg.connect(url,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        conn.execute(Path('campus_attendance.sql').read_text())
    pool=ConnectionPool(url,min_size=1,max_size=8,open=True,kwargs={'row_factory':dict_row,'options':f'-c search_path={schema}'})
    key=Fernet.generate_key().decode();cipher=Fernet(key.encode());terminal_token='t'*40
    settings=Settings(database_url=url,encryption_key=key)
    with pool.connection() as c:
        c.execute("INSERT INTO authorized_terminals(terminal_uuid,token_hash,location_name,direction) VALUES ('gate',%s,'Test gate','IN')",(token_hash(terminal_token),))
        c.execute("INSERT INTO students(student_id,full_name,phone_encrypted) VALUES ('S001','Synthetic Student',%s)",(cipher.encrypt(b'').decode(),))
        c.execute('INSERT INTO student_faces(student_id,embedding_encrypted) VALUES (1,%s)',(cipher.encrypt(json.dumps([0.0]*128).encode()).decode(),))
        c.execute("INSERT INTO admin_users(username,password_hash,role) VALUES ('owner',%s,'owner')", (PASSWORDS.hash('synthetic-password'),))
    client=TestClient(create_app(settings,pool))
    try:
        with client:
            session=client.post('/api/v1/auth/token',json={'username':'owner','password':'synthetic-password'}).json()['access_token']
            yield client,pool,{'x-terminal-uuid':'gate','x-api-token':terminal_token},{'Authorization':'Bearer '+session}
    finally:
        pool.close()
        with psycopg.connect(url,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
