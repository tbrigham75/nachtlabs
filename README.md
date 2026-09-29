# NachtLabs

A Linux-native, self-hosted control plane for governed AI software engineering.

**Source authored through Milestone 10, with the Linux source checks now run.** Lint, type, format, unit, native and web test checks, the production build and the API-client drift check all pass. Deployment, integration, E2E, migration and executor-qualification evidence is still outstanding, so this is not yet a demonstrated release. See the [verification record](docs/planning/linux-verification-2026-09-28.md) for the exact commands, results and environment.

Start with the [full Linux handoff](docs/operations/milestone-10-handoff.md), [current status and limitations](docs/planning/milestone-10-status.md), [acceptance matrix](docs/planning/acceptance-matrix.md) and [results sheet](docs/planning/milestone-10-results.md). Milestone documents are stored under docs/planning; older checkpoint/M4 reports remain historical records.

## Included
- Next.js interface with six themes, authentication/MFA, projects, governance, integrations and scoped service keys.
- FastAPI/PostgreSQL persistence, migration 0003, durable worker, immutable audit and evidence records.
- UI/API/signed-webhook work intake, workflow versions, Mission-aware planning and mandatory human approval.
- Native executor source, local mirror discovery, isolated working copies, cancellation/resource limits and live run events.
- Catalog-backed checks/Journeys, protected holdouts, manual attestations, independent verification and narrow warning exceptions.
- Controlled target Git commit/push/PR adapters, with network-off defaults and uncertain-write recovery.
- Monitoring/system events/incidents, notifications, deterministic approved recommendations, manual regression and retention.
- Linux systemd/configuration/recovery/paired-backup tools, synthetic demo and authored test definitions.

## Boundaries
Target Ubuntu Server 24.04 LTS x86-64, Python 3.12, Node.js 24 LTS, pnpm 10, PostgreSQL 16, systemd and Nginx. Docker is optional and is not required: the control plane (API, worker, interface, database) can run from `compose.yaml`, while the **executor stays native systemd** because its isolation depends on host primitives a container cannot provide — see [ADR 0006](docs/adr/0006-container-deployment.md). Source authoring and the Linux checks run on WSL2, which is adequate for source checks but is not deployment evidence.

Source checks were run on 2026-09-28: lint, type, format, unit, native and web tests, the production build and the API-client drift check pass, as do 76 integration tests against a containerised PostgreSQL. The secret scan, dependency audit, E2E suite and executor qualification still need infrastructure this host does not have and remain NOT RUN. The organization's remote Git restriction remains in force; product adapter source does not authorize live provider use.

API/worker/web use non-root service identities. The native broker is a separate privileged trust boundary; untrusted jobs use isolated DynamicUser services. Execution remains gated on a root-controlled catalog and actual operator qualification. A synthetic adapter does not establish real-agent safety.

## Structure
apps/web: interface. apps/api: HTTP boundary and migrations. apps/worker: mail, probes, workflows and monitoring.
packages/core: policy, identity, adapters, workflow/evidence and Linux executor. packages/api-client: authored browser transport/types.
scripts, systemd, config: native operations. demo: disposable credential-free examples. tests and colocated tests: future operator-run checks.

## First run
Open the configured origin in a browser. The interface checks whether an account exists and, if
none does, takes you straight to Owner setup instead of offering a sign-in form. You type an email
address and a password twice; Organization and Name arrive prefilled and stay editable. That
account becomes the Owner, you are signed in immediately, and first-time setup is then gone from the
sign-in page for good. Later accounts are added by the Owner as invitations under Settings.

If you ever reach `/setup` on an installation that is already initialized, the page says so and
lists the ways forward: sign in, request a password reset, or recover as the operator on the host
console. It never silently redirects you away and leaves you guessing.

If you are locked out and do not know which account exists, `cd /opt/nachtlabs && sudo python3
scripts/recover-owner.py --list` prints the organization and its accounts without changing anything,
so you can then run `--reset-password` against the right address. It loads
`/etc/nachtlabs/migration.env` itself, so it works from a bare `sudo` shell. It will not tell you who
to contact over HTTP: account addresses are never disclosed to an anonymous visitor.

`POST /auth/setup` is intentionally reachable without a secret while uninitialized, so a fresh
installation is usable immediately. On a host reachable from an untrusted network, set
`NACHTLABS_SETUP_TOKEN_REQUIRED=true` and configure `NACHTLABS_BOOTSTRAP_TOKEN_FILE`; setup will
then also require that one-time token. Until the Owner exists, keep the reverse proxy closed to
untrusted clients.

After the first account, setup is closed for good and further accounts are created by the Owner as
**invitations** under Settings. Invariants are delivered by email, so an installation without SMTP
cannot onboard anyone, and password reset is unavailable for the same reason.

If the Owner password is lost and email is not configured, recover it on the host console with
`make recover-owner`. If no account exists at all, the same command with `--bootstrap` creates the
first one.

## Updating an installation
`install-systemd.sh` does not build, so a pulled commit is not compiled. Use `make diagnose-setup`
to check whether the served bundle is current and whether your origin is accepted, then
`make update` to pull, rebuild, restart and health-check. Both are described in
[upgrade and recovery](docs/operations/upgrade-and-recovery.md).

To discard everything and return to a pre-first-run state, `sudo make reset-first-run`. It empties
the database and the build but preserves the credentials and master key under `/etc/nachtlabs`.
Stop and reconcile the executor first. Reset restores runtime database permissions before startup.
Updates prepare a separate build before downtime and retain a recovery copy if activation fails;
see [upgrade and recovery](docs/operations/upgrade-and-recovery.md).

If the first-run form appears but submitting it does nothing, your browser's origin almost certainly
does not match `NACHTLABS_PUBLIC_URL`; `make diagnose-setup` reports the exact mismatch.

## Operator commands
make setup, make configure, make update, make diagnose-setup, make reset-first-run, make recover-owner, make format, make build, make migrate, make install-systemd, make healthcheck, make logs, make api-client, make test, make test-integration, make test-e2e, make lint, make typecheck, make format-check, make migration-check, make api-client-check, make secret-scan, make dependency-audit, make backup and make restore.

Follow handoff ordering. `make lint`, `make typecheck`, `make format-check`, `make build` and `make test` need only Node 24, pnpm 10, Python 3.12 and uv, and pass as of 2026-09-28. `make api-client-check` passes, so the committed OpenAPI schema and TypeScript declarations match the live API; regenerate with `make api-client` only when routes or schemas change. The remaining targets need a database, a running installation or a pinned scanner and remain NOT RUN. The source review is recorded in docs/planning/source-review-m10.md and the executed checks in docs/planning/linux-verification-2026-09-28.md.

To run the control plane in containers, see [container deployment](docs/operations/container-deployment.md). To run it as native services instead, follow the handoff below.

## Documentation
- [Workflow engine](docs/architecture/workflow-engine.md)
- [Independent verification](docs/architecture/independent-verification.md)
- [Git delivery](docs/architecture/git-workflow.md)
- [Manual regression](docs/architecture/regression-workflows.md)
- [API routes](docs/api/workflows.md)
- [Executor qualification](docs/operations/executor-qualification.md)
- [Container deployment](docs/operations/container-deployment.md)
- [Upgrade and recovery](docs/operations/upgrade-and-recovery.md)
- [Working agreement](docs/contributing.md)

The specification is preserved in Original Prompt and the implementation sequence in NachtLabs-Implementation-Plan.md. Source coverage does not mean that runtime acceptance or production readiness has been demonstrated.
