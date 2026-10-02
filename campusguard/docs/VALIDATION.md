# Validation evidence — release 4.0

Revision date: 2026-10-02. All records used here were synthetic. No real camera,
student photograph, biometric cohort or public deployment was used.

## Executed checks

| Check | Result |
|---|---|
| Python suite with native PostgreSQL enabled | **57 passed, 0 skipped**, 6.69 seconds; one TestClient deprecation warning |
| Native PostgreSQL integration subset | 25 tests included in the passing suite: concurrency, retries/conflicts, enrollment rollback, revocation, permissions, accounts, audit, migration preservation, runtime grants and recovery |
| Existing domain/security/queue checks | Passed, including finite vectors, boundaries, encrypted queue restart/retry behavior, body/image limits and failure responses |
| Actual backup drill | `pg_dump` → authenticated encryption → decrypt → `pg_restore` into a new database; verified encrypted phone/templates, attendance, terminal/user/audit counts and revoked restored sessions |
| SQL and dashboard DOM smoke | Passed on PGlite/jsdom; supplemental to native PostgreSQL, not a concurrency substitute |
| Real browser with live API/DB | Passed using Chromium Headless Shell 134 / Playwright 1.51.1: owner login, account creation, audit, logout, viewer restrictions, no stored browser credentials and no JavaScript page errors |
| Mobile layout | Passed at 390 × 844; detected and corrected horizontal overflow, then verified no page overflow |
| Desktop screenshot | Captured at 1440px width using synthetic data; included at `docs/assets/dashboard.png` |
| Synthetic HTTP scan load | 100 requests, concurrency 8, 20 synthetic templates; all HTTP 200; 100 receipts and exactly one new attendance row |
| Production Compose model | Validated by Compose 2.40.3 `config --quiet`; no containers started |
| Caddy configuration | Validated by Caddy 2.9.1; this does not issue or validate a public certificate |
| Prometheus configuration and alerts | Validated by promtool 3.2.1; all four alert expressions parse |
| Source checks | Python compilation, JavaScript syntax, dependency consistency, YAML parsing and release-payload check passed |

The synthetic load completed in approximately 0.549 seconds, with p50 42.9ms
and p95 55.7ms. It intentionally repeated one identity inside the cooldown window:
one new scan was accepted and the remaining decisions were deduplicated. This
short, small-dataset run is not a capacity claim, realistic campus load test,
soak test or accuracy measurement. The script and workload limits are included
so the test can be repeated against a disposable target.

## PostgreSQL test-runtime qualification

This sandbox maps only UID 0. Standard PostgreSQL refuses root startup, and the
environment blocks Unix-domain sockets. For this verification only, PostgreSQL
17.6 was built from its official source with the root-refusal startup guards
removed in `postgres`, `initdb` and `pg_ctl`. It ran on loopback TCP with no Unix
socket directory. SQL execution, transaction/locking logic and storage code were
not changed. Matching `pg_dump`/`pg_restore` came from that build.

This was a temporary test-only runtime. Its binaries, source, database files and
startup modifications are **not included in the project**. Deployment and CI use
standard PostgreSQL container images. Native multi-connection tests now have
actual execution evidence, but this qualified local run does not prove that the
unmodified production image starts in your environment.

The TestClient warning concerns Starlette's future move from httpx to httpx2.
It did not fail a test. Runtime dependency constraints are captured in
`requirements.lock`; the native biometric dependency build remains separate.

## Not executed or still requiring actual environment validation

| Check | Remaining requirement |
|---|---|
| Real face matching and camera pipeline | Install native stack and measure actual camera/lighting/cohort behavior |
| Spoof resistance / presentation-attack detection | No liveness/PAD solution is implemented or verified |
| Docker image build and Compose startup | Docker daemon unavailable locally; startup job is included in CI, but no GitHub run is claimed |
| Public HTTPS certificate issuance / renewal | Verify DNS, firewall, ACME and certificate behavior on the actual host |
| Native release-image workflow / registry publish | Included, not run or published during this editing task |
| Realistic load, sustained soak and failover | Run on target hardware with representative dataset, arrival rate and connection budgets |
| Deployment recovery, off-site backups, RPO/RTO | Repeat protected restore drills using actual host configuration and retention policy |
| Legacy plaintext import / Windows native build | Rehearse against protected copies on the user's actual environment |
| Independent penetration test, MFA/SSO and key rotation | Not implemented/validated by this revision |

## Repeat the checks

From the project root, install `requirements-dev.txt`, configure a disposable
`TEST_DATABASE_URL`, and put matching PostgreSQL backup clients on PATH:

```sh
python -m pytest -q -rs
python -m compileall -q app clients scripts tests
node --check static/app.js
npm ci
npm run test:smoke
python -m scripts.release_check
```

The disposable test role needs permission to create schemas, databases and roles.
Integration tests skip if the database URL is absent; recovery tests also skip
without backup executables. Treat skipped checks as unverified, not passing.
GitHub Actions supplies a standard PostgreSQL 17 service and matching backup
tools, plus a separate container-startup/configuration job. Confirm that workflow
passes after publication before citing CI success.

Use [the operations guide](DEPLOYMENT.md) for host verification. Describe this
release as an engineering portfolio project with implemented operational
controls, not an independently validated production biometric system.
