import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg import Error as DatabaseError
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout
from .biometrics import MAX_IMAGE_BYTES, extract_embedding
from .config import Settings
from .limits import BodyLimitMiddleware
from .auth import install_auth, audit as write_audit
from .monitoring import Metrics, MonitoringMiddleware, configure_logging
from .domain import Scan, day_bounds, fingerprint, nearest_match, status_for, token_hash

logger = logging.getLogger('campusguard')
ROOT = Path(__file__).resolve().parent.parent


def create_app(settings=None, pool=None):
    settings = settings or Settings.from_env()
    configure_logging()
    metrics = Metrics()
    cipher = Fernet(settings.encryption_key.encode())
    owns_pool = pool is None
    db = pool or ConnectionPool(settings.database_url, min_size=1, max_size=settings.pool_size,
                                open=False, timeout=10,
                                kwargs={'row_factory': dict_row, 'connect_timeout': 5,
                                        'options': '-c statement_timeout=10000 -c lock_timeout=5000'})

    @asynccontextmanager
    async def lifespan(app):
        if owns_pool:
            db.open()
            db.wait(timeout=15)
        try:
            with db.connection() as conn:
                row = conn.execute('SELECT version FROM schema_version').fetchone()
                if not row or row['version'] != 3:
                    raise RuntimeError('Initialize or migrate to schema v3 first')
            yield
        finally:
            if owns_pool:
                db.close()

    app = FastAPI(title='CampusGuard', version='4.0.0', lifespan=lifespan,
                  docs_url='/docs' if settings.environment == 'development' else None, redoc_url=None,
                  openapi_url='/openapi.json' if settings.environment == 'development' else None)

    principal, require, authorize_write = install_auth(app, db, settings, metrics)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(MonitoringMiddleware, metrics=metrics)
    app.state.metrics = metrics

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=()'
        response.headers['Cache-Control'] = 'no-store'
        if not request.url.path.startswith('/docs'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.exception_handler(DatabaseError)
    @app.exception_handler(PoolTimeout)
    async def database_error(request, exc):
        metrics.db_errors.inc()
        metrics.ready.set(0)
        logger.error('Database request failed: %s', type(exc).__name__)
        return JSONResponse({'detail': 'Database temporarily unavailable'}, status_code=503)

    @app.exception_handler(InvalidToken)
    async def crypto_error(request, exc):
        logger.error('Encrypted record could not be opened; check key and integrity')
        return JSONResponse({'detail': 'Encrypted data unavailable'}, status_code=503)

    def terminal(x_terminal_uuid: str = Header(default=''), x_api_token: str = Header(default='')):
        if len(x_terminal_uuid) > 100 or len(x_api_token) > 256:
            raise HTTPException(401, 'Terminal authentication required')
        with db.connection() as conn:
            row = conn.execute('SELECT * FROM authorized_terminals WHERE terminal_uuid=%s',
                               (x_terminal_uuid,)).fetchone()
        expected = row['token_hash'] if row else '0' * 64
        if not hmac.compare_digest(expected, token_hash(x_api_token)) or not row or not row['active']:
            raise HTTPException(401, 'Terminal authentication required')
        return row

    def encrypt(value):
        return cipher.encrypt(value.encode()).decode()

    def decrypt(value):
        return cipher.decrypt(value.encode()).decode()

    def audit(conn, action, subject, actor, permission):
        authorize_write(conn, actor, permission)
        write_audit(conn, action, subject, actor)

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        with db.connection() as conn:
            conn.execute('SELECT 1')
        metrics.ready.set(1)
        return {'status': 'ready'}

    @app.get('/metrics')
    def scrape(authorization: str = Header(default='')):
        if not settings.metrics_token or not hmac.compare_digest(token_hash(authorization), token_hash('Bearer ' + settings.metrics_token)):
            raise HTTPException(401, 'Metrics authentication required')
        with db.connection() as conn:
            conn.execute('SELECT 1')
        metrics.ready.set(1)
        return Response(metrics.render(), media_type='text/plain; version=0.0.4; charset=utf-8')

    @app.get('/api/v1/admin/config')
    def config(actor=Depends(require('config.read'))):
        return {'timezone': settings.timezone, 'class_start': settings.class_start,
                'class_end': settings.class_end, 'cooldown_seconds': settings.cooldown_seconds}

    def record_scan(data, auth):
        now = datetime.now(timezone.utc)
        if data.occurred_at > now + timedelta(seconds=60) or data.occurred_at < now - timedelta(days=settings.max_offline_days):
            raise HTTPException(422, 'Scan time outside permitted offline window')
        digest = fingerprint(data, settings.encryption_key)
        with db.connection() as conn:
            # Serialize retries of one request even before we know the matching student.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                         (auth['terminal_uuid'] + ':' + str(data.event_id),))
            # Re-check revocation/direction under lock so configuration cannot change mid-write.
            current = conn.execute('SELECT * FROM authorized_terminals WHERE terminal_uuid=%s FOR SHARE',
                                   (auth['terminal_uuid'],)).fetchone()
            if not current['active'] or current['token_hash'] != auth['token_hash']:
                raise HTTPException(401, 'Terminal authorization changed')
            receipt = conn.execute('SELECT payload_hash,response FROM scan_receipts WHERE terminal_uuid=%s AND event_id=%s',
                                   (auth['terminal_uuid'], data.event_id)).fetchone()
            if receipt:
                if not hmac.compare_digest(receipt['payload_hash'], digest):
                    raise HTTPException(409, 'Event ID was already used for a different payload')
                metrics.scans.labels('replay').inc()
                return receipt['response']
            if data.direction != current['direction']:
                raise HTTPException(409, 'Direction does not match this terminal; review queued events before changing mode')
            templates = conn.execute('SELECT student_id,embedding_encrypted FROM student_faces').fetchall()
            student = nearest_match(data.embedding,
                                    ((r['student_id'], json.loads(decrypt(r['embedding_encrypted']))) for r in templates),
                                    settings.face_threshold, settings.match_margin)
            result = {'success': False, 'event_id': str(data.event_id), 'reason': 'No unambiguous face match'}
            if student is not None:
                # Row lock makes cooldown and insertion atomic across ALL terminals/API workers.
                exists = conn.execute('SELECT id FROM students WHERE id=%s FOR UPDATE', (student,)).fetchone()
                if exists:
                    duplicate = conn.execute('SELECT id FROM attendance_logs WHERE student_id=%s AND check_in_time BETWEEN %s AND %s LIMIT 1',
                                             (student, data.occurred_at - timedelta(seconds=settings.cooldown_seconds),
                                              data.occurred_at + timedelta(seconds=settings.cooldown_seconds))).fetchone()
                    if duplicate:
                        result['reason'] = 'Duplicate scan ignored (cooldown)'
                    else:
                        previous = conn.execute('SELECT event_type,check_in_time FROM attendance_logs WHERE student_id=%s ORDER BY check_in_time DESC,id DESC LIMIT 1', (student,)).fetchone()
                        review = bool(previous and (previous['check_in_time'] > data.occurred_at or previous['event_type'] == data.direction))
                        review = review or (not previous and data.direction == 'OUT')
                        status = status_for(data.direction, data.occurred_at, settings)
                        conn.execute('INSERT INTO attendance_logs(student_id,terminal_uuid,event_id,check_in_time,status,event_type,review_required) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                                     (student, auth['terminal_uuid'], data.event_id, data.occurred_at, status, data.direction, review))
                        result = {'success': True, 'event_id': str(data.event_id), 'status': status,
                                  'event_type': data.direction, 'occurred_at': data.occurred_at.isoformat(),
                                  'review_required': review}
            conn.execute('INSERT INTO scan_receipts(terminal_uuid,event_id,payload_hash,response) VALUES (%s,%s,%s,%s)',
                         (auth['terminal_uuid'], data.event_id, digest, Jsonb(result)))
            metrics.scans.labels('accepted' if result['success'] else 'rejected').inc()
            return result  # connection context commits before the HTTP response is returned

    @app.post('/api/v1/gate/verify-face')
    def verify(data: Scan, auth=Depends(terminal)):
        return record_scan(data, auth)

    @app.post('/api/v1/attendance/auto-scan')
    def auto_scan(event_id: UUID = Form(...), occurred_at: datetime = Form(...),
                  direction: str = Form(...), file: UploadFile = File(...), auth=Depends(terminal)):
        from pydantic import ValidationError
        vector = extract_embedding(file.file.read(MAX_IMAGE_BYTES + 1))
        try:
            scan = Scan(event_id=event_id, occurred_at=occurred_at, direction=direction, embedding=vector)
        except ValidationError:
            raise HTTPException(422, 'Invalid scan metadata') from None
        return record_scan(scan, auth)

    @app.post('/api/v1/admin/register-student')
    def enroll(student_id: str = Form(..., min_length=1, max_length=50),
               full_name: str = Form(..., min_length=1, max_length=100),
               phone_number: str = Form('', max_length=30),
               consent: bool = Form(...), file: UploadFile = File(...), actor=Depends(require('students.write'))):
        if not student_id.strip() or not full_name.strip() or not consent:
            raise HTTPException(422, 'ID, name and recorded consent are required')
        vector = extract_embedding(file.file.read(MAX_IMAGE_BYTES + 1))
        try:
            with db.connection() as conn:
                row = conn.execute('INSERT INTO students(student_id,full_name,phone_encrypted) VALUES (%s,%s,%s) RETURNING id',
                                   (student_id.strip(), full_name.strip(), encrypt(phone_number.strip()))).fetchone()
                conn.execute('INSERT INTO student_faces(student_id,embedding_encrypted) VALUES (%s,%s)',
                             (row['id'], encrypt(json.dumps(vector))))
                audit(conn, 'student.enrolled', row['id'], actor, 'students.write')
        except UniqueViolation:
            raise HTTPException(409, 'Student ID already exists') from None
        return {'success': True, 'message': 'Student enrolled', 'internal_id': row['id']}

    @app.post('/api/v1/admin/register-terminal')
    def register_terminal(terminal_uuid: str = Form(..., min_length=1, max_length=100),
                          api_secret_token: str = Form(..., min_length=32, max_length=256),
                          location_name: str = Form(..., min_length=1, max_length=100),
                          direction: str = Form(...), actor=Depends(require('terminals.write'))):
        if direction not in {'IN', 'OUT'} or not terminal_uuid.strip() or not location_name.strip():
            raise HTTPException(422, 'Valid ID, location and IN/OUT direction are required')
        with db.connection() as conn:
            conn.execute('INSERT INTO authorized_terminals(terminal_uuid,token_hash,location_name,direction) VALUES (%s,%s,%s,%s) ON CONFLICT(terminal_uuid) DO UPDATE SET token_hash=EXCLUDED.token_hash,location_name=EXCLUDED.location_name,direction=EXCLUDED.direction,active=true',
                         (terminal_uuid, token_hash(api_secret_token), location_name.strip(), direction))
            audit(conn, 'terminal.configured', terminal_uuid, actor, 'terminals.write')
        return {'success': True, 'message': 'Terminal configured; token is not returned or stored in plaintext'}

    @app.get('/api/v1/admin/terminals')
    def terminals(actor=Depends(require('terminals.read'))):
        with db.connection() as conn:
            return conn.execute('SELECT terminal_uuid,location_name,direction,active FROM authorized_terminals ORDER BY terminal_uuid').fetchall()

    @app.delete('/api/v1/admin/terminals/{terminal_uuid}')
    def revoke_terminal(terminal_uuid: str, actor=Depends(require('terminals.write'))):
        with db.connection() as conn:
            row = conn.execute('UPDATE authorized_terminals SET active=false WHERE terminal_uuid=%s RETURNING terminal_uuid', (terminal_uuid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Terminal not found')
            audit(conn, 'terminal.revoked', terminal_uuid, actor, 'terminals.write')
        return {'success': True}

    @app.get('/api/v1/admin/students')
    def students(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), actor=Depends(require('students.read'))):
        with db.connection() as conn:
            rows = conn.execute('SELECT id AS internal_id,student_id,full_name AS name,phone_encrypted,created_at FROM students ORDER BY id DESC LIMIT %s OFFSET %s', (limit, offset)).fetchall()
        for row in rows:
            encrypted = row.pop('phone_encrypted')
            row['phone_number'] = decrypt(encrypted) if actor['role'] != 'viewer' else None
        return rows

    @app.delete('/api/v1/admin/students/{internal_id}')
    def delete_student(internal_id: int, actor=Depends(require('students.write'))):
        with db.connection() as conn:
            row = conn.execute('DELETE FROM students WHERE id=%s RETURNING id', (internal_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Student not found')
            audit(conn, 'student.deleted', internal_id, actor, 'students.write')
        return {'success': True, 'message': 'Student, face templates and attendance logs deleted'}

    @app.get('/api/v1/admin/attendance/logs')
    def logs(date: Date | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), actor=Depends(require('attendance.read'))):
        params = []
        query = 'SELECT s.student_id AS roll_number,s.full_name AS name,a.* FROM attendance_logs a JOIN students s ON s.id=a.student_id'
        if date:
            start, end = day_bounds(date, settings.timezone)
            query += ' WHERE a.check_in_time >= %s AND a.check_in_time < %s'
            params += [start, end]
        query += ' ORDER BY a.check_in_time DESC,a.id DESC LIMIT %s OFFSET %s'
        params += [limit, offset]
        with db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            local = row['check_in_time'].astimezone(ZoneInfo(settings.timezone))
            result.append({'id': row['id'], 'student_id': row['roll_number'], 'name': row['name'],
                           'date': local.date().isoformat(), 'actual_entry': local.strftime('%H:%M:%S'),
                           'expected_time': settings.class_start if row['event_type'] == 'IN' else settings.class_end,
                           'attendance': row['status'], 'event_type': row['event_type'],
                           'terminal_uuid': row['terminal_uuid'], 'review_required': row['review_required']})
        return result

    @app.get('/api/v1/admin/dashboard-stats')
    def stats(actor=Depends(require('attendance.read'))):
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        start, end = day_bounds(today, settings.timezone)
        # One statement = one snapshot, avoiding internally inconsistent counters.
        with db.connection() as conn:
            row = conn.execute('''SELECT (SELECT count(*) FROM students) AS total_students,
                count(DISTINCT student_id) FILTER (WHERE event_type='IN') AS today_present,
                count(DISTINCT student_id) FILTER (WHERE event_type='IN' AND status='Late Entry') AS late_entries
                FROM attendance_logs WHERE check_in_time >= %s AND check_in_time < %s''', (start, end)).fetchone()
        row['today_absent'] = max(0, row['total_students'] - row['today_present'])
        return row

    app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
    return app
