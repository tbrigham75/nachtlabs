# Milestone 5: Work intake and durable planning

Source authored on 2026-09-25. **All execution checks: NOT RUN.** Continued under the operator’s authorization to code all milestones without pausing for testing.

## Added
UI/API intake with project-scoped service keys and idempotency; signed GitHub/Gitea issue-comment intake; immutable workflow versions; frozen governance/policy snapshots; model planning; human approval/reject/rework; run views and event history.

## Source map
workflows/policy.py, workflows/state.py, workflows/engine.py; workflow_routes.py; webhook_routes.py; web/features/factory.tsx; migration 0003. Core paths are under packages/core/src/nachtlabs; routes under apps/api/src/nachtlabs_api.

## Deferred operator checks
Replay/conflicting idempotency keys; missing Mission/baseline; revoked membership; webhook bad signature/actor/repository/labels/command; duplicate delivery; Mission conflict; stale approval and policy changes.

Run the applicable make test, make test-integration, make test-e2e, make lint, make typecheck, make build, make migration-check and make secret-scan commands only on the operator’s Linux testing pass. Native security/provider checks additionally require the qualification procedure. No commands in this list were executed during authoring.

## Operator values
Project/Mission/Journey IDs, planning model profile, repository catalog key, webhook secret and explicit actor/label allowlists.

## Handoff
Follow [the full Linux handoff](../operations/milestone-10-handoff.md) and [current limitations](milestone-10-status.md). No commits or remote Git operations were performed. This source report does not close runtime acceptance.
