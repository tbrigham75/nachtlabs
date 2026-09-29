# Development environment

Source authoring and check execution now happen on Linux. Earlier revisions of this document stated that authoring ran on Windows PowerShell without WSL; that is no longer the working environment. The environment used for the 2026-09-28 checks is WSL2 with systemd enabled, which is sufficient for the source-level checks and explicitly **not** sufficient for deployment evidence. Deployment still targets a native Ubuntu 24.04 host, and the systemd, isolation, executor, backup and rotation rows of the acceptance matrix require that host.

The toolchain must match `package.json` engines: Node `>=24 <25` and pnpm `>=10 <11`. A mismatched toolchain makes every `pnpm`-based `make` target fail at startup, which looks like a source fault but is not. Verify with `node -v` and `pnpm -v` before trusting any gate result.

For later non-root Linux development, run `make setup`, create a dedicated PostgreSQL development database and developer-owned credential files, copy `.env.example` to ignored `.env`, and set only non-secret values/credential paths there. Use a localhost origin. Apply migrations with a separate owner credential and runtime grants, then `make dev`. Never use production state in fixtures or run development services as root.

Do not loosen `/etc/nachtlabs` permissions to make a developer shell read production service credentials. Use separate development credentials; use the designated administrative environment for migration/schema-export commands.

Dependency locks and OpenAPI declarations are generated and current: `pnpm install --frozen-lockfile` validates the committed `pnpm-lock.yaml`, and `make api-client-check` confirms `docs/api/openapi.json` and `packages/api-client/src/generated.d.ts` match the live API byte-for-byte. Regenerate with `make api-client` when routes or schemas change, and never hand-edit the generated declarations.
