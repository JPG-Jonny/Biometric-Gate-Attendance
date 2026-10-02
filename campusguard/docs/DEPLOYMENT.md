# Deployment and operations

The implementation provides deployable components and verification tools. The
public-host configuration has not been exercised in this editing environment.
Complete the actual host checks before describing a deployment as production
ready. This is a single-host stack, not a high-availability deployment.

## First deployment

Use a Linux host with Docker Engine/Compose, Python 3.12, adequate memory for
native face extraction, a DNS domain pointing at the host, and inbound TCP
80/443. Do not expose PostgreSQL or the raw API port.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m scripts.deploy init --domain YOUR_DOMAIN --email YOUR_EMAIL
python -m scripts.deploy check
python -m scripts.deploy up --build --first-deploy
```

`init` creates a private `.env` and refuses to overwrite one. Preserve the
biometric and backup encryption keys independently. This creates a new database
volume; it does not attach an existing local `compose.yaml` volume. For existing
installations use an explicit migration/restore plan instead of assuming the
production stack will discover your local data.

The script checks configuration, initializes/migrates schema v3, provisions a
limited `campusguard_api` role, starts the API/proxy/monitoring, waits for container
readiness and verifies HTTPS readiness through your domain. Caddy requests and
renews certificates when DNS and ACME reachability are correct. A configuration
file alone is not evidence that a valid certificate has been issued.

Create the first owner interactively on the server:

```sh
docker compose -f compose.production.yaml run --rm migrate python -m scripts.create_admin YOUR_USERNAME --role owner
```

Then sign in at your configured HTTPS origin. The API container receives only
its runtime DB credentials and biometric/metrics keys. The migration container
has schema-owner credentials. Runtime SQL permits necessary data operations and
audit insertion/reading, but cannot modify schema or erase audit rows. This is
least privilege for this application, not tamper-proof auditing against the
server/database owner.

The production image installs native face extraction by default. Building dlib
needs memory and a compiler; installation must pass on the target builder. CI
also builds a lightweight image with `INSTALL_BIOMETRICS=false` to verify the API
and Compose without equating that with camera validation.

## Versioned releases and upgrades

GitHub Actions runs PostgreSQL tests, recovery checks and SQL/DOM checks. A
separate container job tests startup and proxy/monitoring configuration. The
release-image workflow runs after tests on a version tag or manual invocation,
builds the native image, and publishes a digest to GHCR. GitHub workflows are
included; this package does not claim they have already run on GitHub.

Review changes and migrations, then deploy the immutable digest shown by the
release workflow:

```sh
python -m scripts.deploy up --image ghcr.io/YOUR_USERNAME/campusguard@sha256:ACTUAL_64_HEX_DIGEST
```

The registry must be readable by your host; authenticate Docker for private
packages. Keep the checked-out scripts consistent with the selected release.
Upgrades stop API writes, capture an encrypted pre-deployment dump, apply the
additive migration, provision runtime grants and health-check the new release.
Terminals continue queuing during downtime. The script records the successful
image and verification time locally.

If backup, migration or readiness fails, the command exits with failure. It does
not silently downgrade schema or claim deployment success. Inspect logs and
restore service using the previous compatible image or a recovery database.
A failed pre-upgrade backup can leave the API stopped; restart the previous
compatible service after diagnosing the error. A v3-schema deployment cannot be
rolled back to the old application that requires schema v2 without restoring the
old database and old code together. Do not overwrite the only backup.

## Monitoring

Application requests have a generated `X-Request-ID`. JSON request logs include
route templates, method, status and duration, and exclude request bodies,
credentials and query strings. Launch Uvicorn with `--no-access-log` as in the
image to avoid its independent raw access logging.

`/health/live` checks the API process; `/health/ready` checks PostgreSQL. `/metrics`
requires a separate bearer token and is blocked at the public proxy. Prometheus
scrapes over the private monitoring network and binds its UI to loopback only:
use a server tunnel to port 9090. Do not expose monitoring publicly.

Alert rules detect missing scrapes/database availability, server errors, latency
and repeated login failures. They appear in Prometheus's Alerts page. Routing
notifications to email/Slack/pagers needs your own Alertmanager and destination
configuration; this package sends no external messages.

The image deliberately runs one Uvicorn worker so per-process Prometheus metrics
are coherent. Multiple workers need a Prometheus multiprocess design. Multiple
containers need service discovery/per-instance scraping and measured DB pool
budgets. Caddy has proxy/load-balancing configuration; the default stack has
one API instance and no tested failover capacity. Template matching is O(N).

Login rate buckets are shared in PostgreSQL. Because Uvicorn rejects forwarded
headers by default, behind Caddy the IP bucket is a shared proxy bucket (60
attempts per 5 minutes); username limits remain per account (10 per 5 minutes).
Change trusted-proxy handling deliberately before depending on per-client IP
limits. At most four password verifications run concurrently per process.

## Backups and restore drills

Host utilities need matching PostgreSQL `pg_dump` and `pg_restore` on PATH. Use
an owner-capable backup connection and `BACKUP_ENCRYPTION_KEY` from private
environment/configuration:

```sh
python -m scripts.backup capture backups/backup-UNIQUE_TIMESTAMP.dump.enc
```

Never commit backups. They include sensitive metadata even though the artifact
is encrypted. Preserve a separate protected copy off-host and define retention,
RPO and RTO for your institution. Pre-upgrade dumps are not scheduled backups,
point-in-time recovery or protection from losing the whole host.

The utility keeps a custom-format dump in memory and writes an exclusively
created, authenticated-encrypted file with restrictive permissions. It is
intended for bounded project databases. Use a reviewed streaming/WAL backup
system for large datasets. Back up keys separately: a successful SQL restore
cannot make lost encryption keys recoverable.

Create a **new empty recovery database**. Set `DATABASE_URL` to that database,
use the backup key that created the file, and run:

```sh
python -m scripts.backup restore backups/backup-UNIQUE_TIMESTAMP.dump.enc --confirm-empty-target
```

For container-only DB access, run the restoration from an operator container
with PostgreSQL tools on the private database network, or temporarily use a
protected tunnel. Do not expose port 5432 to the internet.

The restore refuses nonempty targets, authenticates/decrypts the artifact and
uses a single PostgreSQL transaction with errors stopping recovery. Sessions
are deleted afterward so old browser/CLI tokens are revoked. Preserve the
original DB until recovery is checked; reprovision runtime grants, verify
student/template/event counts, decrypt sample synthetic records, inspect audit
history and test API/terminal retry behavior before switching traffic.

The integration suite performs an actual dump/encrypt/decrypt/restore drill
with synthetic students, encrypted templates, attendance and audit records.
That test does not establish your deployment's recovery time or off-site backup
process. Repeat with your own protected environment and restore criteria.

## Routine operations

```sh
docker compose -f compose.production.yaml logs --tail=100 app
# Run periodically under your scheduler after defining operational ownership:
docker compose -f compose.production.yaml run --rm migrate python -m scripts.maintenance --purge-auth --purge-receipts
```

Auth cleanup deletes only expired sessions/rate buckets. Receipt cleanup keeps
one extra day beyond the accepted offline retry window. Student, audit and
attendance retention remain an explicit policy decision. Never run
`docker compose down -v` on a database volume you need.
