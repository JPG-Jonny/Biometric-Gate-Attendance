# Security model and remaining validation

CampusGuard is a portfolio project with implemented reliability and security
controls. It is not a certified biometric access-control product. Keep an
operator-controlled, non-biometric route for attendance or entry decisions.

## Implemented controls

- Individual staff identities, Argon2id password hashes, role permissions and
  attributed audit records. The shared administrator token is removed.
- Random session tokens stored only as hashes in PostgreSQL, absolute expiration
  and revocation after logout, password/role changes or account deactivation.
- HttpOnly, SameSite=Strict browser cookies; Secure on HTTPS origins; CSRF tokens
  on cookie-authenticated mutations and exact Origin checks when present.
- Database-shared sign-in attempt limits, bounded password verification
  concurrency and a last-active-owner invariant protected under a DB lock.
- Hashed per-terminal credentials, constant-time comparisons, explicit direction,
  bounded inputs and request bodies, ambiguity rejection and atomic retry records.
- Authenticated encryption of face templates, optional phone fields, offline
  queued payloads and backup artifacts. Raw enrollment images are not deliberately
  retained; multipart parsing may temporarily spool to disk.
- Same-origin dashboard, CSP and response security headers, no browser
  localStorage/sessionStorage credentials, viewer phone redaction.
- Separate migration/runtime database roles, non-root/read-only API container,
  bounded temporary storage, HTTPS proxy configuration and protected monitoring.

Owners can manage staff; operators can manage students but not terminals/users;
viewers can read gate records and student names/IDs, with phone fields redacted.
Audit attribution is database-backed, but the database owner/server operator can
change audit data. Audit storage is not an immutable external ledger.

## Boundaries that require real-environment work

Face matching is **not liveness verification**. Printed photos, screen/video
replay and other presentation attacks are not prevented. A trusted terminal can
submit arbitrary embeddings/timestamps; a compromised terminal can forge events.
Keep these terminals physically controlled and restrict their network exposure.
Set up and evaluate an actual presentation-attack detection solution before
using this for unattended or consequential decisions. A blink prompt alone is
not demonstrated spoof resistance.

Thresholds are starting values, not measured accuracy guarantees. Evaluate false
accepts/rejects across representative consenting participants, lighting, camera
positions and demographic groups. Maintain human review for ambiguous/unusual
events. No manual historical-correction workflow is implemented.

MFA/SSO, device attestation, independent penetration testing and automatic key
rotation are not implemented. HTTPS configuration still needs valid certificates
on your host. Secure remote PostgreSQL with certificate verification, encrypt
host disks and protect environment files, backups and keys. Define retention,
consent evidence and institutional approval; the consent checkbox alone does
not establish legal compliance.

The included deployment is single-host. Verify resource limits, native image
builds, monitoring alerts, backup retention and restore drills on the actual
host. Alert rules exist, but external notifications require operator configuration.
Synthetic load numbers are not a guarantee of real camera or campus capacity.

## Keys, revocation and recovery

Keep biometric and backup keys separately protected; losing either can make
records unrecoverable. Changing `BIOMETRIC_ENCRYPTION_KEY` also changes receipt
fingerprints and requires a coordinated re-encryption migration. Terminal token
rotation uses the same ID/direction and requires updating the terminal private
configuration; do not change direction with pending events.

Password resets and role/account updates revoke all sessions for the target
staff member. The trusted server-console recovery command resets a password;
there is no public bootstrap endpoint or default account. An initial owner must
be created explicitly after initialization/migration.

Restore into a new database, verify encryption and counts, revoke old sessions
and reprovision runtime grants before traffic switches. The restore utility
revokes restored sessions, but cannot prove your actual RPO/RTO or recover keys
that were not backed up.

## Deletion and reporting

Student deletion cascades current templates and attendance logs. It does not
remove backups, legacy records, independent terminal queues or retained receipt/
audit metadata. Drain or review relevant queues under an explicit retention
policy. SQLite secure-delete is not guaranteed erasure from SSDs or snapshots.

Report vulnerabilities privately to the repository owner through their verified
contact details. Never include passwords, tokens, .env files, face photos,
embeddings, phone numbers or database dumps in public issues.
