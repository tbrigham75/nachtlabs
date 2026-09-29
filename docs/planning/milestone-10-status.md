# Milestones 1–10 source handoff
Date: 2026-09-25. Verification updated 2026-09-28 — see [linux-verification-2026-09-28.md](linux-verification-2026-09-28.md).

The operator authorized coding through every milestone without interim testing and authorized storing milestone documents in this project. This supersedes the old M4 stop.

**Verification status as of 2026-09-28.** The source-level checks have now been executed on Linux and pass: lint, type, format, unit, native and web tests, the production build, and the API-client drift check. Four real defects were found and fixed in the process; they are described in the verification record. What has *not* been executed is everything requiring deployment infrastructure: integration and E2E tests, migrations against a real database, secret and dependency scans, and executor qualification. Those remain NOT RUN, and no acceptance row is marked passed.

## Source delivered in this continuation
- M5: normalized UI/API/signed-webhook intake, project policy, immutable workflow versions, durable runs/events, Mission-aware plan generation and version-bound human decisions.
- M6: PostgreSQL job leasing, one active executor job, root-controlled native broker, independent transient systemd sandboxes, bounded workspace/output/time, cancellation, emergency stop and authenticated SSE replay.
- M7: immutable content/mode candidate manifests, catalog-backed Journey commands, manual attestations, isolated protected checks, independent verifier findings, bounded replan, narrow Owner-approved warning exceptions.
- M8: scope and evidence gates, trusted Git commit construction, pinned HTTPS branch push, GitHub/Gitea PR reconciliation, durable local delivery intent and conservative uncertainty handling.
- M9: monitoring dashboard, structured log filtering/saved views, incidents/timeline/deduplication, in-app/email notification outbox, bounded timeout recommendations with approve/apply/rollback, manual regression and retention.
- M10: executor service/configuration examples, migration/grants/key-rotation updates, encrypted executor-state companion backup, recovery/qualification tools, synthetic demo, additional test definitions and Linux acceptance documents.

See individual milestone-5 through milestone-10 reports and the 33-row acceptance matrix.

## Deliberate limits
This is a **source-verified handoff, not a demonstrated end-to-end release.** Dependency locks and generated API declarations are current and verified. Runtime defects may still remain anywhere a real service, database or browser session is involved; the checks that ran do not cover those paths.

Executor qualification defaults off. The root broker is a privileged trust boundary; API/worker/web remain non-root. Isolated job controls, runtime pins, provider CLI semantics, cgroup egress, cancellation and resource limits require actual Linux evidence before qualification.

Agents receive only working copies; authoritative candidate snapshots and Git are controlled outside agent processes. Hermes telemetry remains opaque. Raw process output is discarded in favor of bounded safe metadata; command exit status is evidence of the registered command, not proof of every business assertion.

The development adapter is a synthetic harness adapter, not a replacement for real-agent qualification. No demo has been run. Git delivery source exists, but all live remote Git activity remains prohibited by the current organization constraint. Local mirrors and direct project-policy agent IDs allow source/validation preparation without provider discovery. PR acceptance remains deferred to an explicitly permitted environment.

Only verifier warnings may be accepted by an Owner when project policy explicitly enables that exception. Required checks, secrets, scope, missing criteria, failed verification and uncertainty cannot be waived. Scheduling, merge/deploy execution, distributed workers and concurrency above one remain disabled/deferred as planned.

## Next evidence
Follow docs/operations/milestone-10-handoff.md and record results against a preserved source snapshot. The source-level gates listed in section 2 of that handoff now pass and can be treated as a baseline; the remaining targets need a real database, a running installation, a pinned scanner and a native Ubuntu host. Do not mark any acceptance row passed from reading source, and do not carry a WSL2 result over as native Linux deployment evidence.
