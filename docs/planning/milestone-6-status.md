# Milestone 6: Native execution and recovery

Source authored on 2026-09-25. **All execution checks: NOT RUN.** Continued under the operator’s authorization to code all milestones without pausing for testing.

## Added
Durable leased jobs; PostgreSQL uniqueness and host flock; bounded native systemd jobs; local mirror discovery; immutable workspace inputs; cancellation/emergency stop; authenticated SSE replay; synthetic development Invocation adapter.

## Source map
execution/catalog.py, process.py, repository.py, sandbox.py, broker.py; systemd/nachtlabs-executor.service; scripts/qualify-executor.py and reconcile-executor.py. Core paths are under packages/core/src/nachtlabs; routes under apps/api/src/nachtlabs_api.

## Deferred operator checks
One active job; broker/worker death; uncertain recovery; cgroup grandchildren; tmpfs/output/memory/process budgets; UID/filesystem/egress isolation; SSE reconnect and session revocation.

Run the applicable make test, make test-integration, make test-e2e, make lint, make typecheck, make build, make migration-check and make secret-scan commands only on the operator’s Linux testing pass. Native security/provider checks additionally require the qualification procedure. No commands in this list were executed during authoring.

## Operator values
Root-owned runtime/catalog/mirror, runtime SHA-256 pins, exact agent/model versions, permitted endpoint pins and completed qualification report.

## Handoff
Follow [the full Linux handoff](../operations/milestone-10-handoff.md) and [current limitations](milestone-10-status.md). No commits or remote Git operations were performed. This source report does not close runtime acceptance.
