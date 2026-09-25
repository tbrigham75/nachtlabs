.PHONY: setup dev build test test-integration test-e2e lint typecheck format format-check migrate migration-check api-client api-client-check secret-scan dependency-audit seed backup restore install-systemd healthcheck logs
setup:
	bash scripts/setup.sh
dev:
	bash scripts/dev.sh
build:
	bash scripts/build.sh
test:
	bash scripts/test.sh unit
test-integration:
	bash scripts/test.sh integration
test-e2e:
	bash scripts/test.sh e2e
lint:
	bash scripts/lint.sh
typecheck:
	uv run --no-sync mypy
	pnpm typecheck
format:
	bash scripts/format.sh write
format-check:
	bash scripts/format.sh check
migrate:
	bash scripts/migrate.sh
migration-check:
	bash scripts/migrate.sh check
api-client:
	bash scripts/api-client.sh
api-client-check:
	bash scripts/api-client.sh check
secret-scan:
	bash scripts/secret-scan.sh
dependency-audit:
	uv run --no-sync pip-audit
	pnpm audit --audit-level high
seed:
	bash scripts/seed.sh
backup:
	bash scripts/backup.sh
restore:
	bash scripts/restore.sh
install-systemd:
	bash scripts/install-systemd.sh
healthcheck:
	bash scripts/healthcheck.sh
logs:
	bash scripts/logs.sh
