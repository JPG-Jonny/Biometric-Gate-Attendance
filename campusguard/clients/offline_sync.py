"""Durable at-least-once delivery; the server deduplicates by terminal + event UUID.
One queue database per terminal identity. Payloads are encrypted; metadata is not.
"""
import argparse
import json
import os
import random
import sqlite3
import time
from contextlib import closing
from pathlib import Path
import requests
from cryptography.fernet import Fernet
from .settings import terminal_settings


class Queue:
    def __init__(self, path, key, terminal_uuid):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(key.encode())
        self.terminal_uuid = terminal_uuid
        with self.connection() as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS queue_identity (id INTEGER PRIMARY KEY CHECK(id=1), terminal TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pending (
                event_id TEXT PRIMARY KEY, payload BLOB NOT NULL, created REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'pending', last_error TEXT);''')
            conn.execute('INSERT OR IGNORE INTO queue_identity VALUES (1,?)',(terminal_uuid,))
            owner = conn.execute('SELECT terminal FROM queue_identity WHERE id=1').fetchone()[0]
            if owner != terminal_uuid:
                raise ValueError('This queue belongs to a different terminal; use a separate queue path')
        if os.name != 'nt':
            os.chmod(self.path, 0o600)

    def connection(self):
        # sqlite3 context alone commits but does NOT close the connection.
        from contextlib import contextmanager
        @contextmanager
        def connect():
            with closing(sqlite3.connect(self.path, timeout=10)) as conn:
                conn.execute('PRAGMA secure_delete=ON')
                with conn:
                    yield conn
        return connect()

    def enqueue(self, payload):
        encoded = json.dumps(payload, sort_keys=True).encode()
        with self.connection() as conn:
            previous = conn.execute('SELECT payload FROM pending WHERE event_id=?', (payload['event_id'],)).fetchone()
            if previous:
                if self.cipher.decrypt(previous[0]) != encoded:
                    raise ValueError('Event ID collision')
                return
            if conn.execute('SELECT count(*) FROM pending').fetchone()[0] >= 10000:
                raise RuntimeError('Queue full; stop scanning and resolve queued/dead events')
            conn.execute('INSERT INTO pending(event_id,payload,created) VALUES (?,?,?)',
                         (payload['event_id'], self.cipher.encrypt(encoded), time.time()))

    def flush_once(self, url, token, session=requests):
        with self.connection() as conn:
            # Purge local payloads after seven days, including quarantined records.
            conn.execute('DELETE FROM pending WHERE created < ?', (time.time()-7*86400,))
            records = conn.execute("SELECT event_id,payload,attempts FROM pending WHERE state='pending' AND next_attempt<=? ORDER BY created LIMIT 10", (time.time(),)).fetchall()
        messages = []
        for event_id, encrypted, attempts in records:
            payload = json.loads(self.cipher.decrypt(encrypted))
            permanent = False
            try:
                response = session.post(url+'/api/v1/gate/verify-face', json=payload,
                                        headers={'x-terminal-uuid': self.terminal_uuid,'x-api-token': token},
                                        timeout=(5,20), allow_redirects=False)
                if response.status_code == 200:
                    result = response.json()
                    if result.get('event_id') != event_id or not isinstance(result.get('success'), bool):
                        raise ValueError('Invalid acknowledgement')
                    with self.connection() as conn:
                        conn.execute('DELETE FROM pending WHERE event_id=?',(event_id,))
                    messages.append(result.get('status') if result['success'] else result.get('reason','Not matched'))
                    continue
                if response.status_code in (401,403):
                    messages.append('Authentication failed; queue preserved. Fix terminal credentials.')
                    break
                permanent = 400 <= response.status_code < 500 and response.status_code not in (408,429)
                error = f'HTTP {response.status_code}'
            except (requests.RequestException, ValueError):
                error = 'Network error or invalid acknowledgement'
            delay = min(300, 2 ** min(attempts+1,8)) + random.uniform(0,2)
            with self.connection() as conn:
                conn.execute('UPDATE pending SET attempts=attempts+1,next_attempt=?,state=?,last_error=? WHERE event_id=?',
                             (time.time()+delay, 'dead' if permanent else 'pending', error, event_id))
            messages.append(('Quarantined: ' if permanent else 'Queued for retry: ') + error)
            if not permanent:
                break
        return messages

    def counts(self):
        with self.connection() as conn:
            return dict(conn.execute('SELECT state,count(*) FROM pending GROUP BY state').fetchall())


def main():
    parser = argparse.ArgumentParser(description='Replay encrypted terminal scans without opening a camera')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    url, terminal, token, _ = terminal_settings()
    queue = Queue(os.getenv('QUEUE_PATH','data/gate_queue.sqlite3'),os.environ['QUEUE_ENCRYPTION_KEY'],terminal)
    if args.status:
        print(queue.counts()); return
    try:
        while True:
            for message in queue.flush_once(url,token):
                print(message)
            if args.once:
                return
            time.sleep(5)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
