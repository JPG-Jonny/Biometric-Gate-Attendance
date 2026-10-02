# Review history

Historical review from release 3.0 (the files listed below were not re-uploaded in this task). Reviewed source: `main(4).py`, `campus_attendance(2).sql`, `AttendanceDashboard(2).jsx`, the supplied standalone HTML, and the enrollment/scanner/terminal/offline scripts. The two `.pyc` files were neither executed nor relied upon; compiled caches are omitted from the repository.

| Original finding | Change |
|---|---|
| Default database password and admin/terminal credentials in code | No operational defaults; generated environment secrets; safe examples and `.gitignore`. Rotate all credentials that existed in the old code. |
| Plaintext terminal tokens and face vectors | Hashed high-entropy terminal tokens; authenticated encryption for templates and optional phone numbers. |
| Repeated scans alternated IN and OUT before cooldown checking | Explicit terminal direction, row-locked cooldown across directions and terminals, face-absence rearming. |
| Check-then-insert race between clients | Database locks, request UUID uniqueness and transactional receipts. |
| Timeout retries could create a second record | Idempotent replay with a keyed payload fingerprint. |
| Offline worker sent incomplete data to nonexistent `verify-face-sync` | Real encrypted queue replaying the implemented verify endpoint with vector, UUID, direction and original timestamp. |
| HNSW index existed, but API fetched every template | Removed misleading vector-index dependency; explained exact encrypted matching and its limit. |
| Naive local timestamps and SQL server CURRENT_DATE | Timezone-aware UTC event storage, configured campus timezone, indexed half-open day filters. |
| Original 09:00 scan was late; later exit status changed after 16:30 | 09:00 is in-time, later IN is late until closing, OUT at/after closing is Exit. Class end configurable (default 16:00 from supplied source). |
| Wildcard credentialed CORS | Same-origin dashboard; no broad CORS exception. |
| React component silently simulated registration after failure; mock values hid zeros | Canonical self-hosted frontend with true errors and zero-safe counters. The divergent JSX is retired rather than shipped as a competing app. |
| Unbounded image read, first of multiple faces accepted | Byte/pixel/type bounds, exactly one face, finite vector validation. Deploying beyond loopback also requires ingress request size/rate limits. |
| Native image/face work inside async endpoints | Synchronous endpoints use FastAPI's worker thread execution; pool bounds database connections. Native work still needs concurrency/load testing. |
| Database exception strings exposed | Generic database errors; logs only exception class for these failures. |
| Missing package/setup/tests/migration guidance | Structured modules, SQL, requirements, examples, CI, tests and non-destructive legacy import. |

## Changed behavior to expect

- The earlier reliability revision was a v2 schema/3.0 application release. Use a new database; the old SQL is not interchangeable.
- A new terminal must be registered before scanning. Old tokens are not imported.
- IN and OUT require distinct configured terminal IDs. For one physical webcam, stop it and switch to a separately registered ID/queue for the other direction.
- Attendance is a gate-event record, not a legal or academic decision about absence.
- Enrollment requires a consent confirmation. Old records are imported only after an explicit operator consent review.
- All faces continue to be represented by the original 128-dimensional face-recognition embedding family. Live matching quality remains unverified here.

## Release 4.0 follow-up

The earlier documented engineering gaps are now implemented: individual
identities/permissions, deployment automation, operational metrics/logging and
broader PostgreSQL/recovery integration coverage. See the current README and
validation report; earlier release findings above are historical context.
