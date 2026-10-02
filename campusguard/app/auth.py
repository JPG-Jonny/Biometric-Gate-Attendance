"""Individual identities, database-backed revocation and cookie CSRF protection."""
import hmac
import secrets
import time
from threading import BoundedSemaphore
from datetime import timedelta
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from psycopg.errors import UniqueViolation

from .domain import token_hash

PASSWORDS = PasswordHasher()
HASH_SLOTS = BoundedSemaphore(4)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
COOKIE = 'campusguard_session'
PERMISSIONS = {
    'viewer': {'config.read', 'students.read', 'attendance.read'},
    'operator': {'config.read', 'students.read', 'students.write', 'attendance.read', 'terminals.read'},
    'owner': {'config.read', 'students.read', 'students.write', 'attendance.read',
              'terminals.read', 'terminals.write', 'users.manage', 'audit.read'},
}


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_.@-]+$')
    password: str = Field(min_length=1, max_length=256)

    @field_validator('username')
    @classmethod
    def normalize(cls, value):
        return value.lower()


class NewUser(Credentials):
    password: str = Field(min_length=12, max_length=256)
    role: Literal['owner', 'operator', 'viewer']


class UserUpdate(BaseModel):
    role: Literal['owner', 'operator', 'viewer'] | None = None
    active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


def password_valid(encoded, password):
    if not HASH_SLOTS.acquire(blocking=False):
        raise HTTPException(429, 'Authentication busy. Retry shortly.', headers={'Retry-After':'2'})
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False
    finally:
        HASH_SLOTS.release()


def audit(conn, action, subject, actor=None):
    conn.execute('INSERT INTO audit_events(action,subject,actor_id,actor_username) VALUES (%s,%s,%s,%s)',
                 (action, str(subject), actor['id'] if actor else None, actor['username'] if actor else None))


def install_auth(app, db, settings, metrics):
    router = APIRouter(prefix='/api/v1')

    def check_origin(request):
        # CLI requests may omit Origin; browser cross-origin requests may not.
        origin = request.headers.get('origin')
        if origin and origin != settings.public_origin:
            raise HTTPException(403, 'Origin rejected')

    def principal(request: Request):
        header = request.headers.get('authorization', '')
        bearer = header.startswith('Bearer ')
        raw = header[7:] if bearer else request.cookies.get(COOKIE, '')
        if not 32 <= len(raw) <= 256:
            raise HTTPException(401, 'Sign in required')
        with db.connection() as conn:
            row = conn.execute('''SELECT u.id,u.username,u.role,u.active,s.csrf_hash,s.token_hash
                FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id
                WHERE s.token_hash=%s AND s.expires_at > now() AND u.active''', (token_hash(raw),)).fetchone()
        if not row:
            raise HTTPException(401, 'Session expired or revoked')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            check_origin(request)
            if not bearer and not hmac.compare_digest(row['csrf_hash'], token_hash(request.headers.get('x-csrf-token', ''))):
                raise HTTPException(403, 'CSRF token required')
        return row

    def require(permission):
        def dependency(actor=Depends(principal)):
            if permission not in PERMISSIONS[actor['role']]:
                raise HTTPException(403, 'Permission denied')
            return actor
        return dependency

    def authorize_write(conn, actor, permission):
        # Hold shared user/session locks until commit, closing the revocation race.
        row = conn.execute('''SELECT u.role FROM admin_users u JOIN admin_sessions s ON u.id=s.user_id
            WHERE u.id=%s AND s.token_hash=%s AND u.active AND s.expires_at > now()
            FOR SHARE OF u,s''', (actor['id'], actor['token_hash'])).fetchone()
        if not row:
            raise HTTPException(401, 'Session expired or revoked')
        if permission not in PERMISSIONS[row['role']]:
            raise HTTPException(403, 'Permission denied')

    def rate_limit(request, username):
        bucket = int(time.time()) // 300
        ip = request.client.host if request.client else 'unknown'
        # Shared across replicas. Commit counting even if authentication fails.
        with db.connection() as conn:
            counts = []
            for identity, maximum in [('ip:' + ip, 60), ('user:' + username, 10)]:
                row = conn.execute('''INSERT INTO auth_rate_limits(bucket_key,expires_at)
                    VALUES (%s,now()+interval '10 minutes') ON CONFLICT(bucket_key)
                    DO UPDATE SET attempts=auth_rate_limits.attempts+1 RETURNING attempts''',
                    (token_hash(str(bucket) + ':' + identity),)).fetchone()
                counts.append((row['attempts'], maximum))
        if any(n > maximum for n, maximum in counts):
            metrics.auth.labels('limited').inc()
            raise HTTPException(429, 'Too many sign-in attempts', headers={'Retry-After': str(300 - int(time.time()) % 300)})

    def login(data, request, response, cookie):
        check_origin(request)
        rate_limit(request, data.username)
        with db.connection() as conn:
            row = conn.execute('SELECT * FROM admin_users WHERE username=%s FOR UPDATE', (data.username,)).fetchone()
            valid = password_valid(row['password_hash'] if row else DUMMY_HASH, data.password)
            if not valid or not row or not row['active']:
                metrics.auth.labels('failed').inc()
                # No database change here; raising safely rolls back this transaction.
                raise HTTPException(401, 'Invalid username or password')
            if PASSWORDS.check_needs_rehash(row['password_hash']):
                conn.execute('UPDATE admin_users SET password_hash=%s WHERE id=%s', (PASSWORDS.hash(data.password), row['id']))
            raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            conn.execute('DELETE FROM admin_sessions WHERE user_id=%s AND expires_at <= now()', (row['id'],))
            conn.execute('''INSERT INTO admin_sessions(token_hash,user_id,csrf_hash,expires_at)
                VALUES (%s,%s,%s,now()+%s)''', (token_hash(raw), row['id'], token_hash(csrf), timedelta(hours=settings.session_hours)))
            # Keep at most ten concurrent sessions per user.
            conn.execute('''DELETE FROM admin_sessions WHERE token_hash IN
                (SELECT token_hash FROM admin_sessions WHERE user_id=%s ORDER BY created_at DESC OFFSET 10)''', (row['id'],))
            audit(conn, 'auth.login', row['id'], row)
        metrics.auth.labels('success').inc()
        user = {key: row[key] for key in ('id', 'username', 'role')}
        if cookie:
            response.set_cookie(COOKIE, raw, max_age=settings.session_hours * 3600, httponly=True,
                                secure=settings.public_origin.startswith('https:'), samesite='strict', path='/')
            return {'user': user, 'csrf_token': csrf}
        return {'user': user, 'access_token': raw, 'token_type': 'bearer', 'expires_in': settings.session_hours * 3600}

    @router.post('/auth/login')
    def browser_login(data: Credentials, request: Request, response: Response):
        return login(data, request, response, True)

    @router.post('/auth/token')
    def cli_login(data: Credentials, request: Request, response: Response):
        return login(data, request, response, False)

    @router.get('/auth/me')
    def me(actor=Depends(principal)):
        return {key: actor[key] for key in ('id', 'username', 'role')}

    @router.post('/auth/logout')
    def logout(response: Response, actor=Depends(principal)):
        with db.connection() as conn:
            conn.execute('DELETE FROM admin_sessions WHERE token_hash=%s', (actor['token_hash'],))
            audit(conn, 'auth.logout', actor['id'], actor)
        response.delete_cookie(COOKIE, path='/')
        return {'success': True}

    @router.post('/auth/password')
    def change_password(data: PasswordChange, actor=Depends(principal)):
        with db.connection() as conn:
            row = conn.execute('SELECT * FROM admin_users WHERE id=%s FOR UPDATE', (actor['id'],)).fetchone()
            authorize_write(conn, actor, 'config.read')
            if not password_valid(row['password_hash'], data.current_password):
                raise HTTPException(401, 'Current password is incorrect')
            conn.execute('UPDATE admin_users SET password_hash=%s WHERE id=%s', (PASSWORDS.hash(data.new_password), actor['id']))
            conn.execute('DELETE FROM admin_sessions WHERE user_id=%s', (actor['id'],))
            audit(conn, 'user.password_changed', actor['id'], actor)
        return {'success': True, 'message': 'Password changed. Sign in again on every device.'}

    @router.get('/admin/users')
    def users(actor=Depends(require('users.manage'))):
        with db.connection() as conn:
            return conn.execute('SELECT id,username,role,active,created_at FROM admin_users ORDER BY id').fetchall()

    @router.post('/admin/users', status_code=201)
    def add_user(data: NewUser, actor=Depends(require('users.manage'))):
        encoded = PASSWORDS.hash(data.password)
        try:
            with db.connection() as conn:
                conn.execute('SELECT pg_advisory_xact_lock(77331003)')
                authorize_write(conn, actor, 'users.manage')
                row = conn.execute('INSERT INTO admin_users(username,password_hash,role) VALUES (%s,%s,%s) RETURNING id,username,role,active',
                                   (data.username, encoded, data.role)).fetchone()
                audit(conn, 'user.created', row['id'], actor)
        except UniqueViolation:
            raise HTTPException(409, 'Username already exists') from None
        return row

    @router.patch('/admin/users/{user_id}')
    def update_user(user_id: int, data: UserUpdate, actor=Depends(require('users.manage'))):
        with db.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(77331003)')
            authorize_write(conn, actor, 'users.manage')
            row = conn.execute('SELECT * FROM admin_users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'User not found')
            role = data.role if data.role is not None else row['role']
            active = data.active if data.active is not None else row['active']
            if row['active'] and row['role'] == 'owner' and (not active or role != 'owner'):
                n = conn.execute("SELECT count(*) AS n FROM admin_users WHERE role='owner' AND active").fetchone()['n']
                if n <= 1:
                    raise HTTPException(409, 'At least one active owner is required')
            conn.execute('UPDATE admin_users SET role=%s,active=%s WHERE id=%s', (role, active, user_id))
            conn.execute('DELETE FROM admin_sessions WHERE user_id=%s', (user_id,))
            audit(conn, 'user.updated', user_id, actor)
        return {'success': True}

    @router.post('/admin/users/{user_id}/reset-password')
    def reset_password(user_id: int, data: PasswordReset, actor=Depends(require('users.manage'))):
        encoded = PASSWORDS.hash(data.new_password)
        with db.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(77331003)')
            authorize_write(conn, actor, 'users.manage')
            row = conn.execute('UPDATE admin_users SET password_hash=%s WHERE id=%s RETURNING id', (encoded, user_id)).fetchone()
            if not row:
                raise HTTPException(404, 'User not found')
            conn.execute('DELETE FROM admin_sessions WHERE user_id=%s', (user_id,))
            audit(conn, 'user.password_reset', user_id, actor)
        return {'success': True}

    @router.get('/admin/audit')
    def audit_events(limit: int = 50, offset: int = 0, actor=Depends(require('audit.read'))):
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(422, 'Invalid pagination')
        with db.connection() as conn:
            return conn.execute('SELECT id,action,subject,actor_id,actor_username,occurred_at FROM audit_events ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s', (limit, offset)).fetchall()

    app.include_router(router)
    return principal, require, authorize_write
