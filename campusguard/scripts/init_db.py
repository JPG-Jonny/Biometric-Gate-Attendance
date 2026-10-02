"""Initialize only an empty target; never drop or overwrite existing tables."""
from pathlib import Path
import psycopg
from app.config import Settings


def main():
    settings = Settings.from_env()
    with psycopg.connect(settings.database_url) as conn:
        count = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
        if count:
            raise SystemExit('Target database is not empty. Use a NEW database for v3.')
        conn.execute((Path(__file__).resolve().parent.parent / 'campus_attendance.sql').read_text())
    print('CampusGuard v3 schema initialized.')

if __name__=='__main__': main()
