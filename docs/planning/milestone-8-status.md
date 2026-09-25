# Milestone 8: Controlled Git delivery

Source authored on 2026-09-25. **All execution checks: NOT RUN.** Continued under the operator’s authorization to code all milestones without pausing for testing.

## Added
Scope/evidence/approval gates; trusted Git object/index/commit construction; deterministic feature branch and commit; pinned HTTPS push without force; GitHub/Gitea PR reconciliation; protected local intent journal and uncertainty handling.

## Source map
execution/delivery.py; integrations/delivery.py; scripts/reconcile-executor.py; run delivery detail. Core paths are under packages/core/src/nachtlabs; routes under apps/api/src/nachtlabs_api.

## Deferred operator checks
Exact candidate tree; secret scan; changed remote base; conflicting branch or ownership marker; provider rejection; interruption after push/PR; duplicate-PR prevention; absence of default-branch writes.

Run the applicable make test, make test-integration, make test-e2e, make lint, make typecheck, make build, make migration-check and make secret-scan commands only on the operator’s Linux testing pass. Native security/provider checks additionally require the qualification procedure. No commands in this list were executed during authoring.

## Operator values
Only in a separately authorized environment: scoped token, qualified remote URL/address, provider/repository binding and provider-network flag. Current organization policy leaves this disabled.

## Handoff
Follow [the full Linux handoff](../operations/milestone-10-handoff.md) and [current limitations](milestone-10-status.md). No commits or remote Git operations were performed. This source report does not close runtime acceptance.
