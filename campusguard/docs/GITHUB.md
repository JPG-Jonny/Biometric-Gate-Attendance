# GitHub publication

Suggested repository: `campusguard`

Description: **Biometric gate attendance with individual staff roles,
transactional PostgreSQL, encrypted offline queues and deployment/monitoring tools.**

Topics: `python`, `fastapi`, `postgresql`, `computer-vision`, `attendance-system`,
`offline-first`, `system-design`, `student-project`, `docker`, `prometheus`.

## Publish the source

Extract the archive and work inside `campusguard`. Create an empty repository
on GitHub first. Replace the username below with your real account.

```sh
git init -b main
git add .
python -m scripts.release_check
git status --short
git diff --cached --stat
git diff --cached
git commit -m "Add staff permissions, deployment, monitoring and recovery tests"
git remote add origin https://github.com/YOUR_USERNAME/campusguard.git
git push -u origin main
```

Review every staged file. The package contains no live credentials, student
photos or database contents; `.gitignore` excludes common private files. Do not
add the original database/uploads as a history folder. Rotate any credentials
previously exposed and use a dedicated history-aware secret scanner before
publishing an existing repository. The included payload check is deliberately
small and does not prove a whole git history is clean.

Choose a license using GitHub's license chooser before calling this open source
or inviting redistribution. No license has been selected on your behalf. Add
the correct repository-owner contact to your public profile for private security
reports. Enable secret scanning/push protection where your account supports it.

Wait for the Tests workflow to finish; it runs PostgreSQL integration/recovery
checks and container configuration/startup checks. It has not run on GitHub while
this package was prepared. The version-tag release workflow publishes a native
image only after tests; review the operation before pushing a release tag.

For a demo, use synthetic IDs/names and hide login credentials, terminal tokens
and configuration. Show staff roles, recorded IN/OUT events, duplicate retries,
offline synchronization and audit attribution. Record real face/camera flow
only after testing the hardware with informed participants.

## Suggested project post

I’ve updated CampusGuard, my AI-assisted biometric gate attendance project,
with a stronger engineering foundation:

- Individual staff accounts, owner/operator/viewer permissions and audit trails
- PostgreSQL transactions and retry-safe attendance events
- Encrypted biometric templates and durable offline synchronization
- Docker deployment tools, HTTPS proxy configuration and protected monitoring
- Integration tests covering concurrent scans, permissions, migrations and
  encrypted backup recovery

This project is helping me learn how systems behave beyond the UI. Real camera
accuracy, spoof resistance and deployment-scale validation are still pending;
I’ve documented the exact checks completed in the repository.

Repository: **add your actual GitHub link after publishing**.

## Suggested first release notes

CampusGuard 4.0 introduces individual staff authentication and revocable sessions,
role permissions, staff-attributed audit history, an additive schema-v3 migration,
a non-root API image, limited runtime DB grants, health-gated deployment,
protected Prometheus monitoring and encrypted backup/restore tools.

See `docs/VALIDATION.md` for executed tests and limitations. Camera liveness,
measured matching accuracy, target-host certificates and realistic campus load
are not claimed as validated.
