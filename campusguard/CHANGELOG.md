# Changelog

## 4.0.0 — Staff access and operations (2026-10-02)

- Replaced the shared admin token with individual Argon2id accounts, revocable
  sessions, owner/operator/viewer permissions and staff-attributed audit records.
- Added HttpOnly browser cookies, CSRF/Origin checks, login throttling, bounded
  verification concurrency and protection for the last active owner.
- Added account management, own-password changes and audit views to the dashboard.
- Added an additive, preservation-tested schema v2 → v3 upgrade.
- Added the non-root API image, full Compose stack, HTTPS proxy, health-gated
  rollout, pre-upgrade encrypted backup and limited runtime database grants.
- Added protected metrics, JSON request logs and Prometheus alert rules.
- Added actual PostgreSQL permission, concurrency, migration and recovery tests,
  synthetic load tooling, CI container checks and a versioned image workflow.
- Updated GitHub publication instructions and the evidence/limitations report.

Breaking change: staff must use individual logins; `x-admin-token` is rejected.
Preserve the original biometric key, back up data and migrate before starting
release 4.0. Camera accuracy/liveness and real deployment validation remain
required.

## 3.0.0 — Reliability and repository revision

- Replaced scan toggling with explicit terminal direction and serialized cooldown checks.
- Added event UUIDs, payload conflict detection and transactional retry receipts.
- Replaced simulated offline sync with encrypted durable delivery and verified acknowledgements.
- Encrypted face templates and phone fields; hashed terminal secrets and removed defaults.
- Added timezone-aware timestamps, campus-day range queries and schedule configuration.
- Added bounded requests/images, ambiguity rejection, same-origin frontend and security headers.
- Consolidated dashboard into local HTML/CSS/JS with explicit errors and terminal management.
- Added v2 schema, non-destructive legacy-copy tooling, tests, CI and architecture documentation.

Breaking changes: new database schema, new secrets, explicit scan metadata and direction, consent required at enrollment, JSX retired in favor of the canonical static dashboard. Migration and native camera validation are required before replacing an active installation.
