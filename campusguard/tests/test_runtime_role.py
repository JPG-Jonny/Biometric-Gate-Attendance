import os
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.errors import InsufficientPrivilege
import pytest
from scripts.provision_runtime import provision

pytestmark=pytest.mark.integration


def test_api_role_can_write_but_cannot_alter_schema_or_erase_audit(system):
    c,p,h,a=system
    role='runtime_'+uuid4().hex
    url=os.environ['TEST_DATABASE_URL']
    with p.connection() as conn:
        schema=conn.execute('SELECT current_schema() AS name').fetchone()['name']
        provision(conn,role,'s'*40,schema)
    try:
        with psycopg.connect(url,autocommit=True) as conn:
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            assert conn.execute('SELECT count(*) FROM students').fetchone()[0]==1
            conn.execute("INSERT INTO audit_events(action,subject) VALUES ('test','synthetic')")
            with pytest.raises(InsufficientPrivilege): conn.execute('DELETE FROM audit_events')
            with pytest.raises(InsufficientPrivilege): conn.execute('ALTER TABLE students ADD COLUMN forbidden text')
            with pytest.raises(InsufficientPrivilege): conn.execute('CREATE TABLE forbidden(id integer)')
    finally:
        with psycopg.connect(url,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
