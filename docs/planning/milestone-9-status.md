# Milestone 9: Monitoring, recommendations and regression

Source authored on 2026-09-25. **All execution checks: NOT RUN.** Continued under the operator’s authorization to code all milestones without pausing for testing.

## Added
Run-state dashboard; safe structured events; project-scoped log filter/saved views; incident correlation/deduplication/timeline; notifications; deterministic bounded timeout recommendation; separate approve/apply/rollback; manual regression; retention windows.

## Source map
monitoring.py; monitoring_routes.py; web/features/monitoring.tsx; execution/retention.py. Core paths are under packages/core/src/nachtlabs; routes under apps/api/src/nachtlabs_api.

## Deferred operator checks
Repeated/new incident transitions; project isolation; stale recommendation/expiry; no change before approval; rollback refuses concurrent edits; manual regression; referenced candidates survive retention; schedules stay off.

Run the applicable make test, make test-integration, make test-e2e, make lint, make typecheck, make build, make migration-check and make secret-scan commands only on the operator’s Linux testing pass. Native security/provider checks additionally require the qualification procedure. No commands in this list were executed during authoring.

## Operator values
SMTP settings for notification outbox; retention periods; regression_enabled project policy; named incident assignees.

## Handoff
Follow [the full Linux handoff](../operations/milestone-10-handoff.md) and [current limitations](milestone-10-status.md). No commits or remote Git operations were performed. This source report does not close runtime acceptance.

M9 system events include periodic worker observations and provider probe outcomes, correlated by safe IDs. They do not scrape arbitrary journald output. Administrators can choose System events in the log explorer; operational-event retention removes old system events while immutable run/audit/evidence history remains retained.
