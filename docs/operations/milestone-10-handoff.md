# Linux handoff: full source, testing deferred
Current state: **NOT RUN**. Target Ubuntu 24.04, Python 3.12, Node 24, pnpm 10, PostgreSQL 16, systemd; no WSL/container requirement. Earlier checkpoint and M4 documents are historical; this is the current handoff.

## 1. Preserve and prepare
Keep this source snapshot and its documents together. No commit is required or authorized. Follow linux-development.md and linux-systemd-deployment.md for native prerequisites and TLS. On the Linux host, generate real dependency lockfiles with the documented setup command. Do not install or start the executor yet.

Review the new bootstrap role nachtlabs_executor, set its password locally, and provision executor-db/executor.env with root-only permissions. Fresh configure.py creates these files; on an existing M4 installation, create only the new files manually rather than rerunning configure.py over existing credentials. Preserve all existing keys and passwords. Run it as `sudo python3 scripts/configure.py --origin https://your-host`; `make configure` prints the exact invocation. It refuses to overwrite existing credentials.

Set both network switches false initially. Supply production HTTPS origin, allowed hosts, database credential file paths, master key/ID, SMTP values where desired, and the separate *_test database credentials. Never put live credentials into the repository.

### First account
Start API, worker and web, open the origin, and you are taken to Owner setup when no account exists. Supply an email address and the password twice; Organization and Name are prefilled and optional. The account becomes the Owner, you are signed in, and first-time setup then disappears from the sign-in page. No setup token is required by default, so do this step while the reverse proxy is still closed to untrusted clients. On an untrusted network, set `NACHTLABS_SETUP_TOKEN_REQUIRED=true` first and use the token that configure.py wrote to `credentials/bootstrap-token`. Setup closes after the first account, permanently: `POST /auth/setup` returns 409 `setup_closed` for every later attempt, and `/setup` then explains the situation rather than redirecting. `make recover-owner` prints recovery commands for a lost Owner password and for bootstrapping the first Owner offline.


## 2. Foundation and source checks
On Linux, in the documented environment, run:
- make setup; make format; make lint; make typecheck; make format-check
- make build; make secret-scan; make dependency-audit
- Apply migration 0003 using make migrate with the migrator configuration, then scripts/grants.sql with the database administrator.
- Apply the same migrations to a disposable database ending _test, then make test and make test-integration.
- make migration-check; make api-client; make api-client-check; make test-e2e.
  `make api-client` is the only supported way to regenerate `docs/api/openapi.json` and `packages/api-client/src/generated.d.ts`; it also runs Prettier, so `api-client-check` compares like with like. If you run `openapi-typescript` by hand you must run `prettier --write` on the output or the check will report a spurious difference.
  `make test-e2e` needs `NACHTLABS_E2E_URL` pointing at an already-running isolated installation. On a host that already has `libnss3`/`libnspr4`/`libasound2` it needs nothing further. On an unprivileged build machine or in a container those are usually absent, Chromium then cannot launch, and every test fails with `error while loading shared libraries` while looking like an application fault; `make test-e2e` calls `scripts/browser-libs.sh`, which fetches only those three packages into the gitignored `.browser-libs` prefix and needs no root. To do it by hand: `export LD_LIBRARY_PATH="$(./scripts/browser-libs.sh)"`.
- Start only API/worker/web, then make healthcheck. Exercise setup/login/MFA/themes/project/governance and service-key revocation.

These are future operator instructions. None ran during authoring. Record actual output, runtime versions, failures and fixes. Resolve foundation errors before proceeding.

## 3. Offline target and native runtime
Create a disposable **local** bare mirror from demo/repository using local Git on Linux. Keep it under /var/lib/nachtlabs-executor/mirrors, root-owned and non-writable by service users. Do not configure a remote for this fixture.

Provision a curated Linux filesystem at /opt/nachtlabs-runtime containing only the required interpreters, libraries, installed agent binaries, gitleaks, trust roots and root-owned check scripts. This is a systemd RootDirectory, not a container runtime. Create /work and /run/nachtlabs/input mount points. Do not bind the host root, control-plane credentials, Docker/system sockets, or unrelated source directories into it.

Install demo/checks/demo_doc.py and demo/checks/gitleaks.toml under /opt/checks inside that runtime. The scanner must use this protected configuration, disable repository ignore files and ignore inline suppression annotations. Configure actual Hermes/OpenCode binaries and their supported model endpoint configuration using version-specific documentation. A generic executable allowlist does not qualify their tool permissions or auto-loading behavior.

Copy config/execution-catalog.example.json to /etc/nachtlabs/execution-catalog.json, root:root 0600. Replace every placeholder. Map local repository key to the project UUID. Put implementation/verifier agent IDs directly in project execution policy when no provider binding is available. Use separate role-specific model profiles and agent configurations.

Catalog agents are keyed by agent UUID; each value must exactly include id, provider, executable, version, expected_version, profile_version, model and role, matching the API configuration. Pin every executable and trusted check script under runtime_files using SHA-256. Avoid symlink executables; use their actual paths. All runtime files/ancestors must remain root-controlled. Changes require new qualification.

Map all automated Journey IDs to catalog command names matching each approved Journey’s command_reference. Map approved protected version IDs under holdout_commands. No user-supplied shell command is accepted. Register checks for each API/browser/integration/external Journey with explicit network needs. External references alone never count as a pass.

## 4. Qualify before enabling
Use executor-qualification.md. Run the isolated native acceptance procedures and record evidence. Confirm the broker mount namespace handoff, UID separation, whole-cgroup termination, memory/process/tmpfs limits, no denied egress, no secret/control-plane access and no repository auto-loaded privileged configuration.

Only after passing, use scripts/qualify-executor.py --evidence /absolute/completed-report.md --confirm-linux-isolation-passed. It records your attestation and does not perform the tests. The example receipt is false and is never installed as a passed receipt. The executor service is installed but not started by the installation script.

Then start the executor explicitly. A catalog change invalidates its receipt; a pinned runtime-file change blocks dispatch. A modified application release requires requalification even when the version string has not yet changed.

## 5. Governed run
Approve a required Journey and Mission. Configure a planning profile and local repository policy. Authorize model-network access only when permitted. Submit the synthetic request, inspect the plan, reject/change/approve it, and verify no implementation runs before approval.

Observe candidate-bound checks, manual attestations, verifier verdicts, SSE reconnect and cancellation. Induce a safe timeout to inspect incident deduplication and the timeout recommendation. Approve, apply and roll back the recommendation; stale policy versions must refuse changes. Run a manual regression. No schedules are enabled.

Current organization policy forbids live remote Git use. Leave Git delivery disabled. Do not bypass the blocked plugin with curl, gh, another API, or a remote runner. Source support for PR delivery does not authorize provider tests. If a permitted environment is explicitly authorized later, qualify each provider and test interruption after push and PR creation.

## 6. Recovery and release decision
Follow upgrade-and-recovery.md, backup-and-restore.md and executor-qualification.md. Test reboot/restart, key rotation and restoration into an isolated *_restore database with a separate executor-state staging directory. Reapply grants; requalify the restored runtime.

Fill milestone-10-results.md and acceptance-matrix.md. No release readiness claim is justified until the actual boundaries have evidence.
