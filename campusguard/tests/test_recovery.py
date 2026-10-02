"""Real pg_dump/pg_restore into temporary whole databases, using synthetic data."""
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from app.auth import PASSWORDS
from app.domain import token_hash
from scripts.backup import capture, restore
from scripts.migrate import migrate

pytestmark=pytest.mark.integration


@pytest.fixture
def recovery_databases():
    url=os.getenv('TEST_DATABASE_URL')
    if not url or not shutil.which('pg_dump') or not shutil.which('pg_restore'):
        pytest.skip('Real PostgreSQL and matching pg_dump/pg_restore are required')
    names=['recovery_'+uuid4().hex for _ in range(2)]
    with psycopg.connect(url,autocommit=True) as conn:
        for name in names:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
    try:
        yield [make_conninfo(url,dbname=name) for name in names]
    finally:
        with psycopg.connect(url,autocommit=True) as conn:
            for name in names:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def seed(url, cipher):
    with psycopg.connect(url) as conn:
        conn.execute(Path('campus_attendance.sql').read_text())
        conn.execute("INSERT INTO students(student_id,full_name,phone_encrypted) VALUES ('S001','Synthetic Recovery',%s)",(cipher.encrypt(b'synthetic-phone').decode(),))
        conn.execute('INSERT INTO student_faces(student_id,embedding_encrypted) VALUES (1,%s)',(cipher.encrypt(json.dumps([0.0]*128).encode()).decode(),))
        conn.execute("INSERT INTO authorized_terminals VALUES ('gate',%s,'Synthetic gate','IN',true)",(token_hash('t'*40),))
        conn.execute("INSERT INTO attendance_logs(student_id,terminal_uuid,event_id,check_in_time,status,event_type) VALUES (1,'gate',%s,now(),'Late Entry','IN')",(uuid4(),))
        conn.execute("INSERT INTO admin_users(username,password_hash,role) VALUES ('owner',%s,'owner')",(PASSWORDS.hash('synthetic-password'),))
        conn.execute('INSERT INTO admin_sessions(token_hash,user_id,csrf_hash,expires_at) VALUES (%s,1,%s,now()+interval \'1 hour\')',(token_hash('test-session'),token_hash('test-csrf')))
        conn.execute("INSERT INTO audit_events(action,subject,actor_id,actor_username) VALUES ('student.enrolled','1',1,'owner')")


def test_encrypted_backup_restore_and_session_revocation(recovery_databases,tmp_path):
    source,target=recovery_databases
    biometric=Fernet(Fernet.generate_key())
    key=Fernet.generate_key().decode()
    seed(source,biometric)
    backup=tmp_path/'recovery.dump.enc'
    capture(backup,key,source)
    assert b'Synthetic Recovery' not in backup.read_bytes() and b'PGDMP' not in backup.read_bytes()
    with pytest.raises(FileExistsError): capture(backup,key,source)
    with pytest.raises(InvalidToken): restore(backup,Fernet.generate_key().decode(),target)
    restore(backup,key,target)
    with psycopg.connect(target) as conn:
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0]==3
        encrypted=conn.execute('SELECT phone_encrypted FROM students').fetchone()[0]
        assert biometric.decrypt(encrypted.encode())==b'synthetic-phone'
        face=conn.execute('SELECT embedding_encrypted FROM student_faces').fetchone()[0]
        assert json.loads(biometric.decrypt(face.encode()))==[0.0]*128
        for table in ['students','student_faces','authorized_terminals','attendance_logs','admin_users','audit_events']:
            assert conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM admin_sessions').fetchone()[0]==0
        assert conn.execute('SELECT actor_username FROM audit_events').fetchone()[0]=='owner'
    with pytest.raises(ValueError,match='empty'): restore(backup,key,target)


def test_additive_upgrade_preserves_existing_students_and_is_idempotent(recovery_databases):
    source,_=recovery_databases
    base=Path('campus_attendance.sql').read_text().split('-- Additive upgrade')[0]+'COMMIT;'
    with psycopg.connect(source) as conn:
        conn.execute(base)
        conn.execute("INSERT INTO students(student_id,full_name,phone_encrypted) VALUES ('S001','Synthetic Existing','untouched')")
    with psycopg.connect(source) as conn:
        assert migrate(conn)
    with psycopg.connect(source) as conn:
        assert not migrate(conn)
        assert conn.execute('SELECT phone_encrypted FROM students').fetchone()[0]=='untouched'
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0]==3
        assert conn.execute('SELECT count(*) FROM admin_users').fetchone()[0]==0
