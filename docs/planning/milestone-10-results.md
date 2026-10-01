# Operator results: Milestones 1–10
Status: native-target-host run (2026-10-01). Control plane + MCP bridge deployed; integration + E2E + migration/roles PASS; real credential mint pending.

Native deployment rows below were filled from an actual run on the **target host**
(openclaw01, Ubuntu 24.04.5, kernel 6.8.0-142-generic, Docker 29.8.1, Compose v5.5.1).
Source-level rows (format/lint/type, secret/dependency scans) retain their WSL2 evidence from
[linux-verification-2026-09-28.md](linux-verification-2026-09-28.md). NOT RUN marks a row that
was not actually executed on this host.

Source snapshot identifier:
Operator/date: hermes-agent / 2026-10-01
Host/distro/kernel/systemd: openclaw01, Ubuntu 24.04.5, Linux 6.8.0-142-generic — **the target host (real host, not WSL2)**
Python/Node/pnpm/PostgreSQL: 3.12.14 / 24.21.0 / 10.0.0 / PostgreSQL via compose `libonion/pglite` one-shot + `postgres` service (healthy)
Generated lockfile identifiers: `pnpm-lock.yaml` validated with `pnpm install --frozen-lockfile` (exit 0)
Agent/model/provider versions: Ollama v0.34.2 at the LAN gateway (text models, provider NOT exercised)
Catalog/runtime hashes: control-plane + mcp images built from current tree at runtime (not pinned here)
Network authorization and explicit exclusions: control plane on `3035`; MCP bridge on `3036`; only loopback + LAN-origin published

| Check | Result | Sanitized evidence / defect |
|---|---|---|
| Setup/build/dependency resolution | PASS (native) | `pnpm install --frozen-lockfile` exit 0; `docker build --target test -f Dockerfile.api` and `docker build -f Dockerfile.mcp` both exit 0; `NACHTLABS_LAN_ORIGIN=… docker compose up -d --build` → api, postgres, web **healthy**, init/roles/migrate/schema-test/grants one-shots all `Exited (0)` |
| Format/lint/type checks | PASS (source) | `make format-check`, `make lint`, `make typecheck` clean (WSL2 source snapshot) — NOT re-run natively this pass; native host has no committed `make` approval path recorded here, so left at prior PASS |
| Unit and PostgreSQL integration tests | Integration PASS; Unit NOT RUN (native) | `docker run --rm --network nachtlabs_backend -v nachtlabs_config:/etc/nachtlabs:ro -e NACHTLABS_TEST_DATABASE_URL_FILE=/etc/nachtlabs/credentials/test-db nachtlabs/test:local /tmp/testenv/bin/python -m pytest -m integration -q` → **79 passed, 1 skipped, 126 deselected** (0:01:40). Unit row retained as WSL2-only (100 passed, 79 skipped) |
| Migration 0003 and least-privilege runtime roles | PASS | one-shots on the live stack all `Exited (0)`: `nachtlabs-migrate`, `nachtlabs-schema-test`, `nachtlabs-roles`, `nachtlabs-grants`, `nachtlabs-init` (init generated credentials, roles created least-priv DB roles, grants applied `scripts/grants.sql`) |
| Browser accessibility/responsive/themes/E2E | PASS | `NACHTLABS_E2E_URL=http://127.0.0.1:3035 npx playwright test` (Playwright 1.63.0, chromium_headless_shell-1243 + headless shell installed) → **49 passed, 1 skipped**. Skip = `e2e/governance.spec.ts` requires `NACHTLABS_E2E_EMAIL` (Owner identity) — expected, not a product defect |
| Authentication/MFA/CSRF/roles/scopes | NOT RUN | |
| Workflow idempotency/approval/webhook boundaries | NOT RUN | |
| Native executor qualification | NOT RUN | executor being containerized in a separate lane (operator decision) |
| Validation/holdout/manual/independent-verifier gates | NOT RUN | |
| Real provider delivery | NOT RUN — organization restriction | |
| Incidents/notifications/recommendation rollback | NOT RUN | |
| Reboot/cancellation/crash reconciliation | NOT RUN | |
| Paired encrypted backup/isolated restore/key rotation | Backup done; encrypted-pair/restore NOT RUN | config volume (holds master key) captured to `/home/tom/backups/nachtlabs/config-volume-<UTC-timestamp>.tar` (tar contains `credentials/master-key` + 16 members). `scripts/snapshot.py` age-path NOT runnable on this host (no `NACHTLABS_BACKUP_RECIPIENT`/`NACHTLABS_MIGRATION_ENV` identity). Isolated restore + key rotation NOT RUN |
| Secret/dependency scans | PASS | gitleaks 8.30.1: no leaks (planted-secret verified). pip-audit: cryptography moved to 50.0.1. pnpm audit: 0 high, 2 moderate dev-only |
| MCP bridge health + verify (agent-driving surface) | PASS — bridge healthy; real credential mint pending | `docker compose --env-file .env.mcp -f compose.mcp.yaml up -d` → `nachtlabs-mcp: Up (healthy)` on `http://127.0.0.1:3036/mcp`, `{"ok": true}` from `/healthz`. Credential files at `/home/tom/nachtlabs-mcp-secrets/{mcp-token,api-key}` owned by uid `9000:9000` mode `400`. `bash scripts/mcp-verify.sh http://127.0.0.1:3036 <token-file>` → **4/5**: checks 1–4 pass (health, auth-required refusal, tool advertisement, upstream reachability); check 5 "live authenticated call" fails because the only credential on host is the expired fixture from the prior machine (and no Owner-minted real key exists yet) — this is EXPECTED per handoff §5.1, not a defect. Real credential mint is a HUMAN browser step (Owner sign-in → create project → POST service-accounts + POST api-keys) and is the ONE outstanding gate |
| All 33 acceptance rows | NOT RUN | every row requires a deployed installation on the target host |

Do not substitute a synthetic adapter result for real Hermes/OpenCode or provider acceptance. Record source fixes and rerun affected checks before changing a result.
