# Development environment

Current source authoring is Windows PowerShell without WSL. Linux scripts and LF sources are supplied, while execution is deferred to the operator. No Windows shim pretends to reproduce Linux service behavior.

For later non-root Linux development, run `make setup`, create a dedicated PostgreSQL development database and developer-owned credential files, copy `.env.example` to ignored `.env`, and set only non-secret values/credential paths there. Use a localhost origin. Apply migrations with a separate owner credential and runtime grants, then `make dev`. Never use production state in fixtures or run development services as root.

Do not loosen `/etc/nachtlabs` permissions to make a developer shell read production service credentials. Use separate development credentials; use the designated administrative environment for migration/schema-export commands.

Generate actual dependency locks and OpenAPI declarations at first handoff, retain them with the local source snapshot, and update through permitted tooling later.
