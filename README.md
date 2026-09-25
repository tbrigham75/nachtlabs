# NachtLabs

A Linux-native, self-hosted control plane for governed AI software engineering.

**Source authored through Milestone 10. All execution checks remain NOT RUN.** This is an unqualified source handoff for the operator’s upcoming Linux testing.

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
Target Ubuntu Server 24.04 LTS x86-64, Python 3.12, Node.js 24 LTS, pnpm 10, PostgreSQL 16, systemd and Nginx. No WSL, Docker, Compose, Kubernetes or Redis requirement. Development here uses PowerShell on Windows.

No dependency installation, application execution, build, test, lint/type/format check, migration, service, health check, scan or live integration probe was performed. No Git initialization, commit or remote operation was performed. The organization’s remote Git restriction remains in force; product adapter source does not authorize live provider use.

API/worker/web use non-root service identities. The native broker is a separate privileged trust boundary; untrusted jobs use isolated DynamicUser services. Execution remains gated on a root-controlled catalog and actual operator qualification. A synthetic adapter does not establish real-agent safety.

## Structure
apps/web: interface. apps/api: HTTP boundary and migrations. apps/worker: mail, probes, workflows and monitoring.
packages/core: policy, identity, adapters, workflow/evidence and Linux executor. packages/api-client: authored browser transport/types.
scripts, systemd, config: native operations. demo: disposable credential-free examples. tests and colocated tests: future operator-run checks.

## Operator commands
make setup, make format, make build, make migrate, make install-systemd, make healthcheck, make logs, make api-client, make test, make test-integration, make test-e2e, make lint, make typecheck, make format-check, make migration-check, make api-client-check, make secret-scan, make dependency-audit, make backup and make restore.

Follow handoff ordering. Generate actual lockfiles and OpenAPI/TypeScript declarations on Linux; none were fabricated. The source-only review is recorded in docs/planning/source-review-m10.md.

## Documentation
- [Workflow engine](docs/architecture/workflow-engine.md)
- [Independent verification](docs/architecture/independent-verification.md)
- [Git delivery](docs/architecture/git-workflow.md)
- [Manual regression](docs/architecture/regression-workflows.md)
- [API routes](docs/api/workflows.md)
- [Executor qualification](docs/operations/executor-qualification.md)
- [Upgrade and recovery](docs/operations/upgrade-and-recovery.md)
- [Working agreement](docs/contributing.md)

The specification is preserved in Original Prompt and the implementation sequence in NachtLabs-Implementation-Plan.md. Source coverage does not mean that runtime acceptance or production readiness has been demonstrated.
