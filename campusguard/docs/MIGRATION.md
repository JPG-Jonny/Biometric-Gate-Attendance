# Migrating to release 4.0

## From the previous package (schema v2)

1. Stop API/collectors and back up the database, application and biometric key.
2. Use the same `DATABASE_URL` and biometric encryption key. Set `PUBLIC_ORIGIN`
   and `METRICS_TOKEN`; remove the obsolete `ADMIN_SECRET_TOKEN` setting.
3. Run `python -m scripts.migrate` with the database owner connection.
4. Run `python -m scripts.create_admin YOUR_USERNAME --role owner` and create
   separate accounts for staff. No shared token is accepted by the new API.
5. Start the new API, sign in and verify existing student/template/log/receipt
   counts. Test account roles and existing terminal identities before resuming.

The additive upgrade creates account/session/rate-limit tables and adds nullable
actor fields to audit records. Existing audit events retain their history without
inventing an individual actor. Student, face, terminal, attendance and receipt
records are preserved. Re-running the migration does not recreate tables.
A synthetic preservation/idempotency integration test is included and executed;
your actual installation still needs a protected migration rehearsal.

The earlier application requires schema v2, so a rollback to that application
requires restoring its pre-upgrade database and code together. Do not attempt a
schema downgrade on live data. The full deployment script handles a pre-upgrade
backup and the additive migration on its own configured database.

## From older plaintext/legacy schemas

The old schema has plaintext vectors/tokens, naive timestamps and `shift_type`. The new schema has encrypted fields, UTC-capable timestamps, consent tracking, explicit terminal directions and receipts. It is intentionally not an in-place `ALTER TABLE` migration.

1. Stop the old scanners/API and make a database backup with your normal PostgreSQL backup tool. Preserve the old application and an independently stored restore copy. Never put the dump on GitHub.
2. Create a new empty database, configure `.env` with NEW secrets and run `python -m scripts.init_db`.
3. For a new demo, simply re-enroll consenting participants in the new dashboard. No import is needed.
4. To copy existing data, review consent for every student first. Set `LEGACY_DATABASE_URL` to the OLD database in your private environment and `DATABASE_URL` to the NEW one. Confirm `CAMPUS_TIMEZONE` matches the timezone the old machine used.
5. Run `python -m scripts.import_legacy --consent-confirmed` from the repository root. Source reads use a read-only repeatable-read transaction; destination writes are a single transaction into empty tables. Do not run enrollment/scanning during import.
6. Verify student/face/log counts, a few timestamps, encrypted fields, and restored attendance history. Rehearse this on a copy first; the import has not been exercised against your actual database.
7. Register fresh terminal credentials and configure separate entry/exit identities. Old tokens are deliberately discarded. The synthetic legacy terminal is revoked.
8. Test entry, exit, duplicates, temporary network loss and a restart before switching over. Keep the old system stopped during validation. Roll back by stopping the new system and restoring the backed-up old installation; do not run both collectors simultaneously.

Historical status strings are preserved, not reinterpreted. All imported logs are flagged for review because the old toggle/cooldown behavior could have produced ambiguous events. Naive old timestamps are interpreted using `CAMPUS_TIMEZONE`; already-aware values preserve their instant. Consent time records the import confirmation, not an invented historic consent time. New internal numeric IDs are assigned; external student IDs are preserved. `shift_type` is removed because there is one configurable campus schedule.

The old `local_gate_cache.db` contained incomplete simulated records without face vectors. It cannot be treated as verified biometric attendance. Review it manually; do not feed it into the new queue. The new client creates `data/gate_queue.sqlite3`.

Keep your original application and backups until the migration has been verified.
