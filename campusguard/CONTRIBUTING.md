# Contributing

Use Python 3.12 and a disposable PostgreSQL 17 database. Install
`requirements-dev.txt`, set `TEST_DATABASE_URL`, and run `python -m pytest -q -rs`.
Matching `pg_dump` and `pg_restore` executables on PATH enable recovery tests.
`npm ci && npm run test:smoke` checks the SQL schema and dashboard DOM.

Use synthetic records in tests and screenshots. Keep secrets, real student
information and biometric templates out of commits, issues and pull requests.
Explain the problem, new behavior and validation in each pull request.

Schema changes must have an additive migration, a preservation test and a
recovery plan. Permission checks belong in the API; hiding dashboard controls
does not enforce access. Do not replace transaction tests with mocked database
calls when testing concurrency or rollback.

The repository owner must choose a license before accepting contributions for
redistribution. No open-source license is selected in this package.
