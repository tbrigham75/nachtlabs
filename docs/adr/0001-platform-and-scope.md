# ADR 0001: native Linux and Checkpoint A

Use Next.js/TypeScript, FastAPI/Pydantic/SQLAlchemy, PostgreSQL/Alembic and a separate Python worker; uv/pnpm and native systemd. No containers or Redis. Windows is authoring only, without WSL.

Initial scope ends at identity/governance/audit/keys. No agent/Git-provider execution exists. Linux tests are operator-owned at the handoff; local source control only. Consequence: dependency/runtime compatibility remains pending, and authored source cannot be labeled demonstrated behavior.

The container exclusion is superseded by [ADR 0006](0006-container-deployment.md): the control plane may run in containers, while the executor remains native systemd because its isolation primitives have no container equivalent. No Redis was ever adopted.
