# Operator results: Milestones 1–10
Status: source checks PASS (2026-09-28); deployment results NOT RUN.

The source-level rows below were filled from an actual run under WSL2, recorded in
[linux-verification-2026-09-28.md](linux-verification-2026-09-28.md). They are not native
Ubuntu evidence. Re-run every row on the target host and replace these entries; leave
NOT RUN where a row was not actually executed.

Source snapshot identifier:
Operator/date:
Host/distro/kernel/systemd: WSL2, Linux 6.18.33.2-microsoft-standard-WSL2, systemd 259 — **not the target host**
Python/Node/pnpm/PostgreSQL: 3.12.14 / 24.21.0 / 10.0.0 / PostgreSQL NOT RUN
Generated lockfile identifiers: `pnpm-lock.yaml` validated with `pnpm install --frozen-lockfile`
Agent/model/provider versions:
Catalog/runtime hashes:
Network authorization and explicit exclusions:

| Check | Result | Sanitized evidence / defect |
|---|---|---|
| Setup/build/dependency resolution | PASS (source) | `pnpm install --frozen-lockfile` lockfile current; `make build` compiled |
| Format/lint/type checks | PASS (source) | `make format-check`, `make lint`, `make typecheck` clean; 87 files formatted, 56 typed |
| Unit and PostgreSQL integration tests | Unit PASS, integration NOT RUN | `make test`: 100 passed, 79 skipped (unit + native + web). Integration needs a real `*_test` database and the three runtime roles |
| Migration 0003 and least-privilege runtime roles | NOT RUN | needs a live PostgreSQL instance and migrator credential |
| Browser accessibility/responsive/themes/E2E | PASS | 50 Playwright tests green against the container stack (2026-09-28). Fixing them exposed 2 product routing bugs and 6 defects in the tests themselves |
| Authentication/MFA/CSRF/roles/scopes | NOT RUN | |
| Workflow idempotency/approval/webhook boundaries | NOT RUN | |
| Native executor qualification | NOT RUN | |
| Validation/holdout/manual/independent-verifier gates | NOT RUN | |
| Real provider delivery | NOT RUN — organization restriction | |
| Incidents/notifications/recommendation rollback | NOT RUN | |
| Reboot/cancellation/crash reconciliation | NOT RUN | |
| Paired encrypted backup/isolated restore/key rotation | NOT RUN | |
| Secret/dependency scans | NOT RUN | `make secret-scan` needs a pinned gitleaks; `make dependency-audit` not executed |
| All 33 acceptance rows | NOT RUN | every row requires a deployed installation on the target host |

Do not substitute a synthetic adapter result for real Hermes/OpenCode or provider acceptance. Record source fixes and rerun affected checks before changing a result.
