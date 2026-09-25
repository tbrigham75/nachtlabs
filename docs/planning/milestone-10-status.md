# Milestones 1–10 source handoff
Date: 2026-09-25. Verification: **NOT RUN — deferred to operator Linux testing.**

The operator authorized coding through every milestone without interim testing and authorized storing milestone documents in this project. This supersedes the old M4 stop. No application, test, build, formatter, linter, type checker, migration, service, health check, scanner, or live integration was executed. No Git initialization, commit, remote operation or PR was performed.

## Source delivered in this continuation
- M5: normalized UI/API/signed-webhook intake, project policy, immutable workflow versions, durable runs/events, Mission-aware plan generation and version-bound human decisions.
- M6: PostgreSQL job leasing, one active executor job, root-controlled native broker, independent transient systemd sandboxes, bounded workspace/output/time, cancellation, emergency stop and authenticated SSE replay.
- M7: immutable content/mode candidate manifests, catalog-backed Journey commands, manual attestations, isolated protected checks, independent verifier findings, bounded replan, narrow Owner-approved warning exceptions.
- M8: scope and evidence gates, trusted Git commit construction, pinned HTTPS branch push, GitHub/Gitea PR reconciliation, durable local delivery intent and conservative uncertainty handling.
- M9: monitoring dashboard, structured log filtering/saved views, incidents/timeline/deduplication, in-app/email notification outbox, bounded timeout recommendations with approve/apply/rollback, manual regression and retention.
- M10: executor service/configuration examples, migration/grants/key-rotation updates, encrypted executor-state companion backup, recovery/qualification tools, synthetic demo, additional test definitions and Linux acceptance documents.

See individual milestone-5 through milestone-10 reports and the 33-row acceptance matrix.

## Deliberate limits
This is an **unqualified source handoff**, not a demonstrated end-to-end release. Dependencies are not installed; real lockfiles and generated API declarations still need the Linux pass. Formatting/type/build/runtime defects may remain.

Executor qualification defaults off. The root broker is a privileged trust boundary; API/worker/web remain non-root. Isolated job controls, runtime pins, provider CLI semantics, cgroup egress, cancellation and resource limits require actual Linux evidence before qualification.

Agents receive only working copies; authoritative candidate snapshots and Git are controlled outside agent processes. Hermes telemetry remains opaque. Raw process output is discarded in favor of bounded safe metadata; command exit status is evidence of the registered command, not proof of every business assertion.

The development adapter is a synthetic harness adapter, not a replacement for real-agent qualification. No demo has been run. Git delivery source exists, but all live remote Git activity remains prohibited by the current organization constraint. Local mirrors and direct project-policy agent IDs allow source/validation preparation without provider discovery. PR acceptance remains deferred to an explicitly permitted environment.

Only verifier warnings may be accepted by an Owner when project policy explicitly enables that exception. Required checks, secrets, scope, missing criteria, failed verification and uncertainty cannot be waived. Scheduling, merge/deploy execution, distributed workers and concurrency above one remain disabled/deferred as planned.

## Next evidence
Follow docs/operations/milestone-10-handoff.md and record results against a preserved source snapshot. Do not mark any acceptance row passed from reading source.
