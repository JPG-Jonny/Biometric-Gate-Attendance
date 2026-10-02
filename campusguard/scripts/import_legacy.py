"""Copy legacy records into an initialized EMPTY v3 database; source is read-only.
Legacy terminal secrets are intentionally not imported. Back up both databases first.
"""
import argparse
import json
import os
from datetime import timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
import psycopg
from cryptography.fernet import Fernet
from app.config import Settings
from app.domain import Scan


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--consent-confirmed',action='store_true',help='Confirm consent has been reviewed for ALL imported students')
    args=parser.parse_args()
    if not args.consent_confirmed:
        raise SystemExit('Review consent before importing. Re-enroll instead if consent is missing.')
    settings=Settings.from_env()
    source_url=os.environ['LEGACY_DATABASE_URL']
    if source_url==settings.database_url:
        raise SystemExit('Source and destination must be different databases')
    cipher=Fernet(settings.encryption_key.encode())
    def enc(text): return cipher.encrypt(text.encode()).decode()
    def aware(dt): return dt.replace(tzinfo=ZoneInfo(settings.timezone)) if dt.tzinfo is None else dt
    with psycopg.connect(source_url) as old, psycopg.connect(settings.database_url) as new:
        old.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        # Lock the destination against concurrent enrollment/imports.
        new.execute('LOCK TABLE students,student_faces,attendance_logs,authorized_terminals IN ACCESS EXCLUSIVE MODE')
        for table in ('students','student_faces','attendance_logs','authorized_terminals','scan_receipts'):
            from psycopg import sql
            if new.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]:
                raise SystemExit('Destination must contain no application records')
        mapping={}
        for ident,roll,name,phone,created in old.execute('SELECT id,student_id,full_name,phone_number,created_at FROM students'):
            row=new.execute('INSERT INTO students(student_id,full_name,phone_encrypted,created_at) VALUES (%s,%s,%s,%s) RETURNING id',
                            (roll,name,enc(phone or ''),aware(created))).fetchone()
            mapping[ident]=row[0]
        for student_id,embedding in old.execute('SELECT student_id,embedding::text FROM student_faces'):
            vector=json.loads(embedding)
            # Validate dimensionality and finite values before import.
            Scan(event_id=uuid4(),occurred_at=__import__('datetime').datetime.now(timezone.utc),direction='IN',embedding=vector)
            new.execute('INSERT INTO student_faces(student_id,embedding_encrypted) VALUES (%s,%s)',(mapping[student_id],enc(json.dumps(vector))))
        legacy_terminal='legacy-import-'+str(uuid4())
        new.execute("INSERT INTO authorized_terminals(terminal_uuid,token_hash,location_name,direction,active) VALUES (%s,%s,'Legacy import','IN',false)", (legacy_terminal,'0'*64))
        count=0
        for student_id,dt,status,direction in old.execute('SELECT student_id,check_in_time,status,event_type FROM attendance_logs ORDER BY check_in_time,id'):
            if direction not in ('IN','OUT'):
                raise ValueError('Invalid legacy event direction; source left unchanged')
            new.execute('INSERT INTO attendance_logs(student_id,terminal_uuid,event_id,check_in_time,status,event_type,review_required) VALUES (%s,%s,%s,%s,%s,%s,true)',
                        (mapping[student_id],legacy_terminal,uuid4(),aware(dt),status,direction))
            count+=1
        new.execute("INSERT INTO audit_events(action,subject) VALUES ('legacy.imported',%s)",(f'{len(mapping)} students; {count} events',))
    print(f'Imported {len(mapping)} students and {count} historical events. Register new terminal credentials.')

if __name__=='__main__': main()
