"""Explicit retention maintenance. No automatic deletion of students or logs."""
import argparse
import psycopg
from app.config import Settings


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--purge-receipts',action='store_true',help='Delete receipts older than the accepted retry window plus one day')
    parser.add_argument('--purge-auth',action='store_true',help='Remove expired sessions and sign-in rate buckets')
    args=parser.parse_args()
    if not (args.purge_receipts or args.purge_auth):
        parser.print_help();return
    s=Settings.from_env()
    with psycopg.connect(s.database_url) as conn:
        if args.purge_receipts:
            result=conn.execute("DELETE FROM scan_receipts WHERE created_at < now() - (%s * interval '1 day')",(s.max_offline_days+1,))
            print('Expired receipts removed:',result.rowcount)
        if args.purge_auth:
            conn.execute('DELETE FROM admin_sessions WHERE expires_at <= now()')
            conn.execute('DELETE FROM auth_rate_limits WHERE expires_at <= now()')
            print('Expired authentication records removed.')

if __name__=='__main__': main()
