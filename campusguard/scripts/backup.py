"""Encrypted custom-format PostgreSQL backups; restore only to an empty DB.

Keeps a dump in memory. For very large databases use a reviewed streaming backup
product; do not silently treat this utility as PITR or off-site retention.
"""
import argparse
import os
from pathlib import Path
import subprocess

from cryptography.fernet import Fernet
from dotenv import load_dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict


def pg_environment(url):
    # Password remains in a child process environment, never command arguments/logs.
    env = os.environ.copy()
    for name, value in conninfo_to_dict(url).items():
        env['PGDATABASE' if name == 'dbname' else 'PG' + name.upper()] = str(value)
    return env


def capture(path, key, url=None, command=None):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command or ['pg_dump','--format=custom','--no-owner','--no-acl'],
                            env=pg_environment(url) if url else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('pg_dump failed; no backup saved. Check connectivity and PostgreSQL client version.')
    encrypted = Fernet(key.encode()).encrypt(result.stdout)
    # Exclusive create prevents overwriting the only backup by mistake.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(encrypted)
        output.flush()
        os.fsync(output.fileno())
    return target.stat().st_size


def restore(path, key, url):
    plain = Fernet(key.encode()).decrypt(Path(path).read_bytes())
    with psycopg.connect(url) as conn:
        n = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')").fetchone()[0]
        if n:
            raise ValueError('Restore target must be empty. Create a new recovery database.')
    result = subprocess.run(['pg_restore','--dbname',conninfo_to_dict(url)['dbname'],'--exit-on-error','--single-transaction','--no-owner','--no-acl'],
                            input=plain, env=pg_environment(url), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('pg_restore failed; recovery database was not committed')
    # Dump includes sessions; restored tokens must never become valid again.
    with psycopg.connect(url) as conn:
        conn.execute('DELETE FROM admin_sessions')
        conn.execute('DELETE FROM auth_rate_limits')


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['capture','restore'])
    parser.add_argument('file')
    parser.add_argument('--confirm-empty-target', action='store_true')
    args = parser.parse_args()
    key, url = os.environ['BACKUP_ENCRYPTION_KEY'], os.environ['DATABASE_URL']
    if args.operation == 'capture':
        capture(args.file, key, url)
        print('Encrypted backup saved. Keep its key and biometric key separately.')
    else:
        if not args.confirm_empty_target:
            raise SystemExit('Set DATABASE_URL to a NEW empty recovery database and pass --confirm-empty-target')
        restore(args.file, key, url)
        print('Restore completed. Sessions revoked. Verify records and encryption before switching traffic.')


if __name__ == '__main__':
    main()
