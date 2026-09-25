# Checkpoint A status

Handoff **checkpoint-a-2026-09-25**: **Ready for operator testing — execution checks not run.**

| Area | Source authored | Verification |
| --- | --- | --- |
| M1 | Monorepo/manifests, API/web/worker, PostgreSQL/Alembic, native config/scripts/services | NOT RUN |
| M2 | Owner bootstrap, sessions/CSRF, MFA/recovery, invites/reset, roles, shell/themes | NOT RUN |
| M3 | Projects/membership, Mission/Journey versions/approval, encrypted holdouts, keys/audit/OpenAPI | NOT RUN |
| Operations | Separate roles, email outbox/heartbeat, encrypted snapshots/alternate restore | NOT RUN |
| Tests | Core security, PostgreSQL boundaries/race, frontend forms, browser governance | AUTHORED; NOT RUN |
| Source review | Inspected/edited source, intended contracts and access boundaries | Source observations only |

Pending: dependency resolution/locks, formatting, configuration, migration/grants, generated OpenAPI/declarations, build/startup, manual acceptance and automated checks. No fabricated build output, screenshot, coverage or passing result is supplied.

## Scope/limitations

- No M4 or later integrations, agents, workflows, remote Git/PR delivery, insights or schedules. Worker cannot dispatch execution.
- Browser transport/types are authored; generated OpenAPI declarations will accompany them after the operator generation step.
- Compiler/dependency compatibility, migration drift, systemd hardening, layout/accessibility and runtime behavior are unverified. First execution may identify corrections.
- MFA uses manual TOTP-key entry/provisioning URI; no QR image renderer.
- Journeys support configured execution methods and manual/historical source references. Actual execution/run-backed import waits for M7.
- One organization is explicitly enforced; multi-organization operation is later work. Roles are fixed, not user-defined.
- Email is at-least-once: a crash after SMTP acceptance may duplicate the same single-use link. Jobs have bounded retries; delivery UI is later work.
- Keys expose M3 read scopes only. They cannot approve changes or impersonate humans.
- Audit append-only controls protect against runtime identities, not host/database administrators. No audit purge UI exists.
- Key rotation implementation waits for M4. Never overwrite the active master key; existing encrypted data needs it.
- No Git repository initialization, commits, remote Git, or CI actions occurred. Files are local workspace source.

Attach operator results to a local snapshot/handoff revision. Do not relabel user-reported outcomes as independently verified.

Historical Checkpoint A report. The operator subsequently authorized M4 source without testing; see milestone-4-status.md for current scope and limitations.
