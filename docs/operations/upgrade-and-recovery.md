# Upgrade, interruption and recovery
Status: authored procedure; NOT RUN.

## Routine update to a new commit
`install-systemd.sh` installs users, directories and units. It deliberately does **not** build, so a
pulled commit is never compiled and `git pull` on its own changes nothing an operator can see. A
stale web bundle is the most common cause of "the first-run setup form is missing".

Diagnose first; it is read-only and safe at any time:

    make diagnose-setup

It reports the installed commit against its upstream, whether the served standalone bundle contains
the first-run setup marker, whether static assets were copied, the raw `/auth/setup-status` payload,
and unit state. A stale bundle is reported as such.

Then update:

    make update

That target refuses to start unless the working tree is clean, no executor broker is running, and a
`nachtlabs-api.service` unit is installed. It stops API, worker and web; fetches and fast-forwards
only; runs `uv sync --locked` and `pnpm install --frozen-lockfile`; runs `scripts/build.sh`; starts
the services; and runs `make healthcheck`. It never reads, writes or migrates anything under
`/etc/nachtlabs`, so credentials, the master key and service env files are untouched, and it
discards no local edits.

Two deliberate stops. If the range introduces a new Alembic revision under
`apps/api/migrations/versions`, the target lists it and exits rather than applying it; review and
apply it deliberately with migrator credentials (`sudo -u nachtlabs_migrator make migrate`). If the
tree is dirty, it exits rather than clobbering local work.

Use `make build` rather than `pnpm build`. The standalone output does not contain `.next/static`
unless `scripts/build.sh` copies it, and the web unit serves from
`/opt/nachtlabs/apps/web/.next/standalone/apps/web/server.js`; without the copy, JavaScript is
served as HTML and the page fails with `SyntaxError: Unexpected token '<'`.

After updating, reload in a private window so no cached bundle is used. On a fresh installation the
first load must show "Initialize NachtLabs". If it shows a plain sign-in form on an installation with
no account, run `make diagnose-setup` again and read the bundle line.

## Upgrade from M4
Stop API, worker, web and executor. Preserve an encrypted database/key snapshot using the matching pre-upgrade release (the M4 snapshot tool expects schema 0002). Retain that release and real lockfiles. Provision the new executor database role and root-only credential/env files. Install reviewed source/dependencies, apply migration 0003 with migrator credentials, reapply scripts/grants.sql and run the Linux checks on an isolated test database.

Do not downgrade by deleting evidence tables. If migration/build/runtime acceptance fails, restore the paired pre-upgrade backup and old release to a separate environment before switching traffic. Keep executor and provider-network gates off until qualification.

## Interrupted execution
Only one broker may hold its local flock; PostgreSQL also enforces one claimed/running job. A job owns a random lease. The broker records the current transient unit before launch, renews leases while commands run, and marks interrupted outcomes uncertain rather than redispatching writes.

On restart it stops the recorded cgroup and unmounts verified orphan workspaces. An uncertain run requires local operator review. Stop the executor and use scripts/reconcile-executor.py JOB_UUID --reason 'actual investigation summary' --confirm-executor-stopped. For non-delivery jobs this records failure, after which the UI can request a new plan within its budget. It never fabricates success.

Delivery intent is under /var/lib/nachtlabs-executor/delivery. An already completed journal can be reconciled into the database. If interruption occurred after a network mutation but before its result was durably recorded, leave the run uncertain until the remote is examined in an authorized environment. Do not create a replacement run or blindly retry a push while its outcome is unknown. The provider adapter can reconcile an existing owned PR, but automatic replay of ambiguous writes is intentionally disabled.

## Paired backup
Stop all services for a consistent backup window. Run the current database/key backup (schema 0003, format 2) and scripts/executor-state.py backup --archive NEW.tar.age --recipient AGE_RECIPIENT --services-stopped before restarting. The companion includes candidates, local mirrors, delivery journals and catalog. Keep both archives under one operator-generated backup identifier.

Restore the database into a new *_restore database, keys to new protected files, and executor state with scripts/executor-state.py restore --archive ARCHIVE --identity IDENTITY --destination /absolute/new-staging-directory --services-stopped. The tool refuses live-state replacement and unsafe archive members. Confirm every referenced candidate digest and delivery record against the restored DB before installing staged state. Reapply grants. Runtime binaries are reprovisioned separately; no qualification receipt is restored.

Use encrypted storage for broker candidates: repository contents can contain sensitive data even when raw process logs are discarded. Never copy candidate archives into a web-served directory.

## Encryption rotation
Stop every service including executor, take both backups and use offline migrator credentials. rotate-master-key.py now rewraps run evidence and executor results in the same transaction as identity, integration and mail secrets. Only the migrator temporarily disables the evidence immutability trigger for ciphertext rewrapping; content hashes are unchanged. Update API/worker/executor/migration environment files together before restart.
