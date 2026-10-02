"""Bootstrap or recover an individual account from a trusted server console."""
import argparse
import getpass
import psycopg
from app.auth import NewUser, PASSWORDS, audit
from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('username')
    parser.add_argument('--role', choices=['owner', 'operator', 'viewer'], default='owner')
    parser.add_argument('--reset-password', action='store_true', help='Recover an existing account and revoke every session')
    args = parser.parse_args()
    password = getpass.getpass('New password (12+ characters, hidden): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match')
    data = NewUser(username=args.username, password=password, role=args.role)
    with psycopg.connect(Settings.from_env().database_url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(77331003)')
        if args.reset_password:
            row = conn.execute('UPDATE admin_users SET password_hash=%s,active=true WHERE username=%s RETURNING id',
                               (PASSWORDS.hash(data.password), data.username)).fetchone()
            if not row:
                raise SystemExit('User does not exist')
            conn.execute('DELETE FROM admin_sessions WHERE user_id=%s', (row[0],))
            action = 'console.password_reset'
        else:
            row = conn.execute('INSERT INTO admin_users(username,password_hash,role) VALUES (%s,%s,%s) RETURNING id',
                               (data.username, PASSWORDS.hash(data.password), data.role)).fetchone()
            action = 'console.user_created'
        audit(conn, action, row[0])
    print('Account saved. Password and session tokens were not printed.')


if __name__ == '__main__':
    main()
