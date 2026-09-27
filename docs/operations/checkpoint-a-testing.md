# Checkpoint A — operator Linux testing

**Foundation procedure retained for the current M4 handoff. All execution checks NOT RUN.** Read [M4 changes and restrictions](milestone-4-handoff.md) first.

Use a disposable Linux VM/host with synthetic identities/projects. The coding agent now stops after M4 and does not execute these commands. No remote Git, WSL, or containers are involved.

## 1. Prerequisites and transfer

Ubuntu Server 24.04 LTS; PostgreSQL 16 and clients; system Python 3.12 at `/usr/bin/python3.12`; Node.js 24 LTS; pnpm 10; uv; Git for local use only; Bash, Make, OpenSSL, curl, Nginx, age, build-essential, pkg-config, libpq headers. Install through your organization's permitted sources. A reviewed gitleaks binary is needed for later scans.

Copy source by your permitted file-transfer method into `/opt/nachtlabs`. Preserve LF endings. Bash invokes the scripts, so missing executable bits on a Windows copy are acceptable. Do not copy credentials from another installation. Record tool versions in the results template. The web unit expects `/usr/bin/node`; adjust it if your approved root-owned Node binary is elsewhere.

## 2. Resolve dependencies and format

As an authorized installation user, in `/opt/nachtlabs`:

```bash
make setup
make format
```

Setup creates real `uv.lock` and `pnpm-lock.yaml` when absent, then installs dependencies. Retain both with the local source snapshot. Registry package access is required; no Git remote is used. Formatting was deliberately deferred to this operator step. If resolution fails, stop and return the sanitized error; do not force a different major version or replace PostgreSQL with SQLite.

## 3. Provision Linux/DB identities

Review and run:

```bash
sudo bash scripts/install-systemd.sh
sudo -u postgres psql -f scripts/bootstrap-db.sql
sudo -u postgres psql
```

At the PostgreSQL prompt, assign distinct passwords interactively:

```text
\password nachtlabs_migrator
\password nachtlabs_api
\password nachtlabs_worker
\q
```

Passwords do not belong in shell arguments/history or source. Bootstrap creates roles without default passwords and without superuser privileges. Service installation creates accounts and units but does not start them.

## 4. Protected configuration

Replace the placeholder origin/SMTP settings with your actual test configuration:

```bash
sudo /opt/nachtlabs/.venv/bin/python scripts/configure.py \
 --origin https://nachtlabs.example.invalid \
 --smtp-host smtp.example.invalid --smtp-port 587 \
 --smtp-tls starttls --smtp-from nachtlabs@example.invalid
```

For SMTP auth, add `--smtp-username`; its password is requested privately. The script also requests the three DB passwords from step 3, generates the master key/bootstrap token, and stores protected files under `/etc/nachtlabs`. It prints no secrets and refuses to overwrite existing configuration. Production settings intentionally reject `.invalid` origins: substitute a real configured host.

A loopback alternative is `--development --origin http://localhost:3000`. A local mail catcher may use `--smtp-host 127.0.0.1 --smtp-port 1025 --smtp-tls plain`; it must actually be running for email tests. Plain SMTP is rejected in production. Do not expose development HTTP publicly.

Review `api.env`, `worker.env`, `web.env`, and `migration.env` in `/etc/nachtlabs`. Web receives no database/master key. API and worker have different DB roles. Preserve the master key for encrypted-data recovery.

## 5. Migrate, grant, generate, build

In an administrator shell with your approved uv/pnpm on PATH:

```bash
export NACHTLABS_ENV_FILE=/etc/nachtlabs/migration.env
make migrate
sudo -u postgres psql -d nachtlabs -f scripts/grants.sql
make api-client
make build
```

The migration file is not readable by runtime identities. API-client generation exports OpenAPI and creates `packages/api-client/src/generated.d.ts` without starting a server. The build creates Next standalone output and copies static assets. These are first compilation/generation attempts, not repeats of verified runs.

Stop on failure. Record command/tool versions, sanitized output, and handoff ID. Do not continue from a failed build or partial schema.

## 6. TLS and services

Review `config/reverse-proxy/nachtlabs.conf`; supply your hostname and trusted TLS certificate paths. Install using your normal Nginx administrator procedure, validate its configuration, then reload. Only the proxy should listen externally; API/web bind to loopback.

```bash
sudo systemd-analyze verify systemd/nachtlabs-api.service systemd/nachtlabs-worker.service systemd/nachtlabs-web.service
sudo systemctl enable --now nachtlabs-api nachtlabs-worker nachtlabs-web
sudo env NACHTLABS_ENV_FILE=/etc/nachtlabs/migration.env bash scripts/healthcheck.sh
sudo bash scripts/logs.sh
```

Expected: services active, liveness `alive`, readiness `ready`/schema `0002`, login page visible. The authenticated overview must show recent heartbeat. A running process alone is not proof. Inspect effective service accounts and permissions using the hardening guide.

## 7. Identity checks

Retrieve `/etc/nachtlabs/credentials/bootstrap-token` locally as administrator. The `/setup` page asks for it as "Setup token" only when the installation was configured with `NACHTLABS_SETUP_TOKEN_REQUIRED=true`; on a default installation the field is absent and you supply nothing. If a submission is refused for a missing token, the field appears and explains where the token lives. Create a synthetic Owner with a unique strong password. Never include credentials, MFA material or recovery codes in screenshots/logs you return.

- First setup creates the Owner; a second attempt is rejected.
- Login/logout work and logged-out sessions cannot read `/api/v1/auth/me`.
- Protected navigation requires login; no public registration exists.
- Security settings enroll TOTP via manual key entry and current-code confirmation.
- Save the ten one-time recovery codes privately; test that reuse fails.
- Invite a Viewer and Contributor via email and verify the assigned roles.
- Reset links expire/are single-use; reset revokes sessions without removing MFA.
- Enable privileged MFA policy only after the acting Owner is enrolled. Unenrolled Admins must enroll.
- The last active Owner cannot be disabled or demoted.

SMTP and the worker must work for mail. A queued invitation is not proof of delivery; there is no fake-success adapter.

## 8. Interface and themes

Select all six themes under Appearance: Midnight Operations, Graphite, Light Canvas, Forest Terminal, Nordic Frost, Solarized Workshop. Confirm preference persists after reload/sign-in. Check Follow system, command palette (Ctrl/Cmd+K), account menu, keyboard/focus, mobile navigation, dialog dismissal, errors/tables, zoom, contrast and reduced motion. No browser/visual checks were performed during authoring.

## 9. Governance

1. Create a draft project, e.g. `Acceptance Lab` / `acceptance-lab`.
2. Add a manual Journey: authorized sign-in reaches overview. Fill steps, expected outcomes, evidence and owner.
3. Approve Journey v1.
4. Draft a Mission with scope, non-goals, constraints, escalation, unacceptable changes and that approved baseline Journey. Approve it.
5. Edit a new version. History remains; the older approved version stays active until approval changes.
6. From two tabs, try a stale edit/approval. Expect conflict, not overwrite.
7. Add a synthetic protected holdout. Owner/Admin may view it; other roles and API keys may not. Project/audit responses must omit its content.
8. Grant an invited user access to one project; another unassigned project must remain inaccessible. Use separate browser sessions.
9. Archive/restore the project; archived governance edits should be rejected.

Definitions are stored, not executed. No Journey, holdout, agent, repository command or target commit can run here. Last-run data is absent instead of a fabricated pass.

## 10. API keys and audit

Create a service account and a key restricted to one project and `projects:read`. Save the raw value privately; reloading cannot retrieve it. Verify permitted reads, rejection of another project/admin endpoints, and immediate revocation. Rotation shows a new value once and limits the old key's remaining life to 24 hours or its earlier expiry.

Use an approved API client with an Authorization header, never a URL token. Audit should attribute setup, role/membership, governance, approvals and key events without exposing secrets or unauthorized project records. Export is JSON capped at 1,000 authorized records; use cursor pagination for larger sets.

## 11. Automated checks you may invoke on Linux

These are separate from manual browser evidence and have not been run by the coding agent:

```bash
make lint
make typecheck
make format-check
make test
make migration-check
make api-client-check
make secret-scan
make dependency-audit
```

Integration fixtures truncate data ONLY in a dedicated database ending `_test`. Never use the application database. Create fresh `nachtlabs_test` owned by a test schema-owner role, store its URL in a protected file, and apply `0002` there using the migration credential variable. Set `NACHTLABS_TEST_DATABASE_URL_FILE` to that file and run `make test-integration`. Keep the worker away from the test database. The test identity needs ownership for fixture reset and trigger assertions.

Browser tests need a separate already-running test installation with a disposable Owner whose MFA is disabled for that fixture. Supply `NACHTLABS_E2E_URL`, `NACHTLABS_E2E_EMAIL`, `NACHTLABS_E2E_PASSWORD` through your protected local environment. Install Chromium dependencies with `pnpm exec playwright install --with-deps chromium`, then run `make test-e2e`. Recording/traces/screenshots are disabled to avoid automatic credential capture. The test creates synthetic projects and leaves them in history.

Skipped tests are not passes. Click-through cannot prove race prevention or DB immutability; record those as not run unless separately exercised.

## 12. Persistence, recovery, results

Restart services; projects, preferences, versions and audit should persist. Perform encrypted backup/alternate-database restore on a separate disposable target before claiming recovery works.

Fill `docs/planning/checkpoint-a-results.md` with actual outcomes, commands, versions and sanitized errors. Exclude cookies, tokens, `.env` contents, keys, recovery codes, holdout details and raw emails. Request fixes or explicitly request continuation. The coding agent stops here and does not begin M5 automatically.
