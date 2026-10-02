# Why these architecture choices?

A technology list is not an architecture. Choose a mechanism for an actual failure mode, explain its tradeoff, and test it. This project is a modular single API with PostgreSQL and trusted camera clients. It is a portfolio prototype, not a certified biometric access-control product.

| Reel concept | Meaning | Decision in CampusGuard |
|---|---|---|
| ACID | Atomicity, consistency, isolation and durability of transactions | PostgreSQL transactions commit enrollment plus templates together; scan result plus idempotency receipt commit together. Foreign keys, unique keys and row locks enforce invariants. Durability also depends on database/storage configuration and backups. |
| Encryption | Protecting data using keys | Fernet authenticated encryption for face templates, optional phone numbers and queued scan payloads. Random terminal tokens are SHA-256 hashed, not encrypted. Use HTTPS for traffic and encrypted disks/backups. |
| RabbitMQ | A message broker | Not installed. There is no asynchronous downstream email/notification service yet. A broker alone would not solve duplicate attendance records. Add one only with a concrete background-work requirement. |
| DynamoDB | A managed key-value/document database | Not installed. PostgreSQL fits students, templates, logs, uniqueness and transactional joins. Moving to a second database adds consistency and operating work without solving a measured problem here. |
| Load balancer | Distributes requests among API instances | Caddy proxies the container API and has load-balancing policy configured; one API instance is the default. The database owns idempotency and locking, so later API replicas can share state. HTTPS configuration, request limits, monitoring and deployment checks are implemented. Capacity and failover still need target-host testing. |
| Consistency | What different clients can observe and when | Primary PostgreSQL handles accepted events. Per-student locks serialize cooldown checks; per-request advisory locks serialize retries. Offline terminals are eventually synchronized. Original event times are retained; unusual arrival/order sequences are flagged for review. |
| Indexing | Extra structures that speed selected queries | Indexes support student/time cooldown lookups, date-range logs and receipts. Unique indexes prevent duplicate IDs. The old HNSW vector index was unused because Python loaded every vector. This version encrypts templates and intentionally uses exact O(N) matching. |
| Message queues | Retain work until a consumer handles it | SQLite queue at each terminal encrypts payloads, persists before sending, retries with backoff, verifies acknowledgements and quarantines permanent failures. At-least-once delivery plus server idempotency gives one attendance write for a retried event, not universal exactly-once delivery. |
| CDN | Caches/distributes static content near users | Not necessary for a local administrative app. Dashboard JS/CSS are self-hosted. Do not put authenticated attendance data or biometrics into a public CDN cache. FastAPI's optional `/docs` UI still uses its upstream documentation assets. |

## Scan path

1. A trusted, registered camera terminal sees one face, creates an event UUID and UTC timestamp, and encrypts the event into its local SQLite queue.
2. A worker sends it to the authenticated API. Network failures leave the same event intact for retry.
3. The API validates metadata and time window, locks the request ID and checks its stored receipt.
4. It validates terminal direction and matches decrypted face templates. Ambiguous matches are rejected.
5. It locks the matched student row, checks for any event within the cooldown window, then writes the event and receipt in one transaction.
6. Only a valid acknowledgement with the matching event ID removes the queue record. A negative match is also a completed decision, not a transport failure.

No automatic IN/OUT toggling exists. Each terminal is configured for one direction. A face must leave the camera view for at least two seconds before another event is captured. This is duplicate reduction, **not liveness detection**.

## Consistency boundaries

- Default PostgreSQL READ COMMITTED plus explicit locks is used; we do not claim serializable isolation for every operation.
- An exact retry returns its first decision even if templates were later changed/deleted. The receipt carries no student name or face vector. Expired events are rejected before replay; receipt cleanup retains one extra day beyond the retry window.
- A conflicting payload reusing an event ID returns HTTP 409. Direction mismatch also returns 409 and requires operator review; do not switch a terminal's direction while it has queued events.
- Revoked terminals cannot replay receipts. Token rotation requires updating the terminal environment. Reusing the same ID with the same direction preserves queued events.
- Offline events may arrive in a different order than they occurred. Logs retain their timestamps and flag anomalies; no claim of perfectly reconstructed occupancy or classroom attendance is made. Cooldown uses absolute event-time proximity, so the first accepted event wins even if a later arrival was captured earlier.
- Dashboard counters are one SQL snapshot. The counters and separate paginated table requests may differ briefly during incoming scans. Offset pagination may move under concurrent inserts; this is not a fixed-snapshot export.
- Late entries count students with any late IN event today, including re-entry. “Entered today” does not mean “currently inside”.

## Matching and encryption tradeoff

Encrypted face vectors cannot be indexed by ordinary pgvector HNSW. This version decrypts templates in application memory and computes exact distances; it favors an explicit confidentiality boundary over an unused performance feature. Names, student IDs, event times and audit metadata remain database-readable. Encrypt the database disk and backup files as well.

Do not claim a supported student count or requests/second without measurement. Before larger deployment, benchmark on the actual device and cohort. Options include identity-claimed 1:1 matching, a carefully governed in-memory index with invalidation, or plaintext vectors inside a separately secured matching service. Each changes the threat model.

The default distance threshold is 0.50 with a 0.05 runner-up margin. These are configurable starting values, **not measured accuracy guarantees**. The old 0.77 threshold was permissive compared with the library's 0.6 default. Evaluate false accepts/rejects using consented representative data before real use.

## If background notifications are added

Insert an outbox row in the same PostgreSQL transaction as the event. An outbox dispatcher may publish to RabbitMQ with publisher confirms. A consumer acknowledges only after completion and uses a unique delivery key. Expect redelivery; define retry/dead-letter policy and monitoring. This is a future design, not implemented functionality.

## Primary references consulted

- PostgreSQL row locking: https://www.postgresql.org/docs/17/explicit-locking.html
- PostgreSQL indexes: https://www.postgresql.org/docs/17/indexes.html
- Fernet authenticated encryption: https://cryptography.io/en/stable/fernet/
- RabbitMQ reliability and redelivery: https://www.rabbitmq.com/docs/reliability
- DynamoDB consistency: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html
- Face-recognition tolerance: https://face-recognition.readthedocs.io/en/latest/face_recognition.html

## Staff identities and operational controls (release 4.0)

Passwords use Argon2id; each random browser/CLI session is hashed in PostgreSQL
with a bounded absolute lifetime. Cookie mutations require a session-specific
CSRF token. Role permissions are checked in the API, and mutations recheck
session/role state under shared database locks before committing audit records.
Account management serializes the active-owner invariant using an advisory lock.
Updating passwords, roles or account activation revokes target sessions.

Caddy terminates HTTPS, while the default single-worker API provides isolated
Prometheus metrics and JSON logs with bounded route labels. Deployment initializes
or migrates schema and provisions a limited API role. Existing installations get
an encrypted pre-upgrade backup. Readiness failure stops the deployment command;
it does not silently perform an unsafe database downgrade.

Primary implementation references:

- Argon2 password hashing: https://argon2-cffi.readthedocs.io/en/stable/api.html
- Caddy automatic HTTPS: https://caddyserver.com/docs/automatic-https
- PostgreSQL dump/restore: https://www.postgresql.org/docs/17/backup-dump.html
- Prometheus configuration: https://prometheus.io/docs/prometheus/latest/configuration/configuration/
