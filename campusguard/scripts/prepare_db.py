"""Idempotent deployment setup: initialize an empty DB or migrate v2."""
from pathlib import Path
import psycopg
from app.config import Settings
from .migrate import migrate


def main():
    with psycopg.connect(Settings.from_env().database_url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(77331002)')
        exists = conn.execute("SELECT to_regclass('schema_version')").fetchone()[0]
        if exists:
            migrate(conn)
        else:
            n = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
            if n:
                raise SystemExit('Database contains unrecognized tables; deployment stopped')
            conn.execute((Path(__file__).resolve().parent.parent/'campus_attendance.sql').read_text())
    print('Schema v3 ready.')


if __name__ == '__main__':
    main()
