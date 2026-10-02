"""Use the migration/owner connection, never the API role. Does not print secrets."""
import os
import psycopg
from psycopg import sql
from app.config import Settings


def provision(conn, role, password, schema='public'):
    if len(password) < 32:
        raise ValueError('Runtime database password must have 32+ characters')
    if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    conn.execute(sql.SQL('ALTER ROLE {} PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(sql.Identifier(role), sql.Literal(password)))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
    for table in ['students','student_faces','authorized_terminals','attendance_logs','scan_receipts','admin_users','admin_sessions','auth_rate_limits']:
        conn.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON {}.{} TO {}').format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)))
    for table, permissions in [('audit_events', 'SELECT,INSERT'), ('schema_version', 'SELECT')]:
        conn.execute(sql.SQL('GRANT '+permissions+' ON {}.{} TO {}').format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)))
    conn.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))


def main():
    settings = Settings.from_env()
    with psycopg.connect(settings.database_url) as conn:
        # Prevent the runtime role from creating objects through PostgreSQL public privileges.
        conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        provision(conn, 'campusguard_api', os.environ['RUNTIME_DB_PASSWORD'])
    print('Runtime role provisioned with table permissions and no schema-management privileges.')


if __name__ == '__main__':
    main()
