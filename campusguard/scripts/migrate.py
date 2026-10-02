"""Apply the additive v2 -> v3 upgrade; never recreate application tables."""
from pathlib import Path
import psycopg
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def migrate(conn):
    conn.execute('SELECT pg_advisory_xact_lock(77331002)')
    version = conn.execute('SELECT version FROM schema_version FOR UPDATE').fetchone()[0]
    if version == 3:
        return False
    if version != 2:
        raise RuntimeError('Only schema v2 can be upgraded; use the legacy import guide for older data')
    conn.execute((ROOT / 'migrations/003_accounts.sql').read_text())
    return True


def main():
    with psycopg.connect(Settings.from_env().database_url) as conn:
        changed = migrate(conn)
    print('Upgraded to schema v3.' if changed else 'Schema v3 already current.')


if __name__ == '__main__':
    main()
