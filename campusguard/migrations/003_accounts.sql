-- Additive upgrade from schema v2; run with scripts.migrate, inside its transaction.
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version = 3;
ALTER TABLE schema_version ADD CHECK (version = 3);
CREATE TABLE admin_users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username varchar(100) UNIQUE NOT NULL CHECK (username = lower(username)),
    password_hash text NOT NULL,
    role varchar(10) NOT NULL CHECK (role IN ('owner', 'operator', 'viewer')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE admin_sessions (
    token_hash char(64) PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    csrf_hash char(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX admin_sessions_user_idx ON admin_sessions(user_id);
CREATE INDEX admin_sessions_expiry_idx ON admin_sessions(expires_at);
CREATE TABLE auth_rate_limits (
    bucket_key char(64) PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 1,
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_rate_expiry_idx ON auth_rate_limits(expires_at);
ALTER TABLE audit_events ADD COLUMN actor_id bigint;
ALTER TABLE audit_events ADD COLUMN actor_username varchar(100);
CREATE INDEX audit_events_time_idx ON audit_events(occurred_at DESC, id DESC);
