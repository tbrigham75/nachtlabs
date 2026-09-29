# Upgrade, interruption and recovery
Status: authored procedure. The update/reset/activation **shell orchestration** is now covered by executed checks under WSL2 (16 passing tests in `tests/native/test_maintenance_scripts.py`, including activation failure, interrupted-activation recovery and successful promotion). A real update against an installed deployment has **not** been run; that needs a native Ubuntu host with systemd, a live database and a real remote.

## Host-console scripts and configuration
An installed deployment keeps its configuration in `/etc/nachtlabs`, not in the repository, and a
bare `sudo python3 scripts/thing.py` inherits no environment. Every host-console script that reaches
the database therefore loads `/etc/nachtlabs/migration.env` itself, and the shell targets fall back
to it when there is no repository `.env`. Nothing is overridden: a variable already present in the
environment always wins, and `NACHTLABS_OPERATOR_ENV_FILE` selects a different file.

If a script reports that no configuration was found, the installation has never been configured:

    sudo python3 scripts/configure.py --origin https://your-host

## Lost Owner access
First find out what exists. This is read-only and changes nothing:

    cd /opt/nachtlabs
    sudo python3 scripts/recover-owner.py --list

It prints the organization and every account with role and active state. This exists because
`--email` is mandatory for any recovery and the interface deliberately will not disclose account
addresses to an anonymous visitor, so an operator who had lost both the address and the password had
no supported route in and the host console was the only option.

Then either keep the installation and reset the credential:

    sudo python3 scripts/recover-owner.py --email <address> --reason "why" --reset-password

or start over with `make reset-first-run` below. Resetting a password is the better choice when the
data matters: it revokes existing sessions, clears any MFA enrolment so you can enrol again, and
records `identity.owner.recovered` in the audit trail.

If no account exists at all, `--list` says so and points at `--bootstrap`, which creates the first
Owner. It refuses when any account row already exists.

## Start over: reset to a pre-first-run state
If an installation is in a state where the first-run page will not behave, discard everything and
begin again:

    sudo make reset-first-run

This empties the database, re-applies migrations **and runtime database permissions**, deletes the
web build, rebuilds, and health-checks the restarted installation. The next page load offers Owner
setup. These revised procedures and their regression tests are authored and were executed on 2026-09-28
under WSL2; the reset and update flows against a real installed deployment remain untested.

It checks everything before changing anything, and refuses unless it is root, the tree is
`/opt/nachtlabs`, the working tree is clean, and a systemd unit is installed. It proves the **build
toolchain** is present and correct first — Node 24, pnpm 10, uv — because the rebuild replaces the
bundle it deletes, and a build that cannot succeed must not begin by tearing down what works. It
prints the row counts it is about to destroy, requires you to type `RESET`, and requires `--force` if
anything beyond a first account exists: runs, evidence, integrations or audit history.

Stop the executor and reconcile its jobs before resetting. The command holds the broker lock,
refuses remaining execution units or `active.json`, and refuses claimed, running or uncertain jobs
even with `--force`. It also refuses unknown database activity and failed service stops. Activity is
checked again after the API and worker stop, in the same transaction as schema deletion. Use
`sudo bash scripts/reset-first-run.sh --force` when intentionally discarding recorded activity;
the `RESET` confirmation is still required.

After migrations, the command restores schema usage and applies `scripts/grants.sql` before any
service restart. It does not grant runtime roles ownership or evidence-update privileges. A failure
before startup leaves services stopped and names the failed phase. If reset already committed,
complete migrations and restore permissions from a root shell with the migration environment:

    cd /opt/nachtlabs
    set -a; source /etc/nachtlabs/migration.env; set +a
    .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
    .venv/bin/python scripts/maintenance_db.py grants
    .venv/bin/python scripts/maintenance_db.py check-migrations
    make build
    systemctl start nachtlabs-api nachtlabs-worker nachtlabs-web
    make healthcheck

Resolve the reported error before using this sequence; it does not restore deleted data. Keep the
executor stopped. Database credentials are read from files and are never passed as command arguments.

It does **not** touch `/etc/nachtlabs`. Credentials, the master key and every service env file are
preserved, so `configure.py` does not need to run again and no secret is rotated. A reset is
therefore a way to fix application state, not to recover a lost credential; for that use
`make recover-owner`.

Note that `organizations` has a `singleton` constraint, so an installation can only ever hold one
organization. If setup reports that an account already exists, one does: both code paths that create
an organization create its Owner in the same transaction, and no migration, seed or script inserts one
on its own. `recover-owner.py --list` will show you which.

Deleting `apps/web/.next` matters. A stale bundle is the most common reason a first-run page appears
not to update, because `install-systemd.sh` does not build.

## Why a working form can still fail to submit
A first-run form that renders but does nothing is nearly always an origin mismatch, and it is
invisible in the status endpoints. `GET /auth/setup-status` is a GET, so it answers 200 with
`{"initialized": false}` and the installation looks healthy, while every POST that would create the
account is refused with `403 origin`. `browser_origin` requires the request `Origin` to equal
`NACHTLABS_PUBLIC_URL` exactly, so `https://nachtlabs.example.com` configured against a browser on
`https://www.nachtlabs.example.com` fails every write and no read.

The interface now says so itself. A signed-in page whose address is not in the permitted set shows
a persistent banner naming the address in use, every accepted origin, and the setting to change, and
the setup wizard turns the refusal into the same advice instead of passing the bare message through.
A form that renders and then refuses is still worth checking here, but it should now say why.

## Connecting a model server on your own network
The model endpoint is not this host. It is whatever machine runs Ollama, and the
address the connection stores is the one the API and worker dial, which has to be
reachable from the machine running NachtLabs rather than from wherever the
browser happens to be. The browser never contacts it: the interface is served
with `connect-src 'self'`, and discovery runs in the worker while the planning
call runs in the API.

Two rules decide whether a remote endpoint can be saved at all, and the setup
wizard now checks both before sending anything, because the API cannot report
why it refused: pydantic's own reason is suppressed so submitted values cannot be
echoed, which left a refused endpoint reading only as "Check the indicated
fields" with no field named.

Plain HTTP is accepted for a loopback address, and for an address on your own
network only when `NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true` is set in
**both** `api.env` and `worker.env`, since the discovery check and the planning
call each build their own connection. The transport has no fallback and never
disables verification. A non-globally-routable address also needs "Permit this
private or loopback address", which includes loopback, since `127.0.0.0/8` is
not globally routable either.

The switch is off by default and reaches your own network and no further: a
publicly routable address still requires `https://` with the switch on. It
changes only the scheme requirement, so the connection's own permissions, the
single approved pin, the reserved and metadata address classes and the no-DNS
rule are all unaffected.

Cleartext costs more than confidentiality, and it is worth being exact about
what is exposed. The request carries the work instruction, the Mission,
Journeys, allowed paths, validation commands and repository metadata, and
anything on the network path can read all of it. The reply is the part that
matters more: it is parsed as the plan and becomes the recorded plan for a
governed run, so with HTTPS forging it needs the server's certificate key, and
here it needs only network position. The pinned address is the only thing
between a run and the network. If the network is shared, put a reverse proxy in
front of a loopback provider: the same endpoint configuration then works while
the traffic stays on the host, which is the stronger arrangement and needs no
switch. The wizard and the Integrations screen both say so on an endpoint that
is configured this way, permanently rather than as a one-time confirmation.

Because no DNS is ever resolved, the origin and the pin are independent: the
origin supplies the `Host` header and the TLS name, and the pin is the numeric
address actually connected to. A hostname in the origin with a different pin is
valid and is the right shape for a stable address; a certificate for a bare IP
must carry that IP as a subject alternative name, and the certificate authority
that issued it has to be trusted via `NACHTLABS_INTEGRATION_CA_FILE` in **both**
`api.env` and `worker.env`, since the discovery check and the planning call each
build their own connection. Certificate verification was confirmed to work
against an IP subject alternative name with no name resolution involved, and a
mismatched address fails closed with `certificate verify failed: IP address`, so
an address change means reissuing the certificate and editing the connection.

This is a control-plane arrangement only. Agents do not run against a private
address until the root execution catalog lists it with `allow_private_network`,
and because the catalog digest is bound to the qualification receipt, that re-opens
`scripts/qualify-executor.py`.

## Answering on more than one address
`NACHTLABS_PUBLIC_URL` is the canonical origin: it builds the links in reset and delivery email, and
it is the one production mode requires to be HTTPS. Additional browser addresses go in
`NACHTLABS_ALLOWED_ORIGINS` as a comma-separated list of full origins:

    NACHTLABS_PUBLIC_URL=https://nacht.lan
    NACHTLABS_ALLOWED_ORIGINS=https://lab.lan,https://nacht.lan:8443
    NACHTLABS_ALLOWED_HOSTS=nacht.lan,lab.lan

Three things are enforced at startup rather than discovered later as a puzzling failure:

- every origin's hostname must also appear in `NACHTLABS_ALLOWED_HOSTS`, or the request passes the
  origin check and is then rejected by the trusted-host middleware with an unexplained 400;
- production requires every permitted origin to be HTTPS, not just the canonical one;
- one hostname may not be permitted on two schemes at once. A `Secure` cookie set on 443 is never
  sent on 80 while a non-`Secure` one is sent on both, so the pair behaves unpredictably. Use a
  distinct hostname, or serve that host on HTTPS only.

The list widens the set of addresses that work; it never opens it to others. Matching is exact and by
membership, so a prefix or a lookalike host such as `https://nacht.lan.evil.example` does not
satisfy it. If any permitted origin is plain HTTP, the session cookie is issued without the
`Secure` attribute so that origin stays usable, and the interface says so; serve every permitted
origin over HTTPS to get it back. Widening the list also widens who can reach an installation, so on
one that is not yet initialized set `NACHTLABS_SETUP_TOKEN_REQUIRED=true` and restart before doing so,
or anyone who can reach the new address can create the Owner account.

`make diagnose-setup` reports the whole set and probes `/auth/preflight` once per permitted origin,
so a wrong entry is caught from the host. It calls that public, non-mutating endpoint, which reports
the origin it saw, the canonical origin, the full permitted list and whether they match. Note that
`origin_accepted` there is only meaningful when the request actually carried an `Origin` header: a
same-origin `GET` from a browser never does, so reading it from the interface's own page always shows
`null` even on a healthy installation. To reproduce a host mismatch deliberately:

    NACHTLABS_DIAGNOSE_ORIGIN=https://www.example.com make diagnose-setup

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

    sudo make update

Run from a root shell whose PATH includes Node 24, pnpm 10 and uv. The target requires a clean
`/opt/nachtlabs` checkout, an upstream branch, installed service units, and a stopped, reconciled
executor. It reads migration credentials from the trusted environment file but does not modify
credentials, keys, service environment files or the database schema.

While the existing API, worker and web remain available, it fetches the upstream revision, verifies
fast-forward ancestry, extracts that exact revision into `/opt/nachtlabs-update.*`, resolves locked
dependencies there, and builds the web application. Preparation failures leave the installed release
and its services alone. The staged Python environment only warms the dependency cache; it is never
copied into the installation because its editable paths refer to the staging directory.

The migration check compares the **database's applied Alembic revisions** with the target release,
both before downtime and after activation. A repeated attempt or previously pulled source cannot
bypass it. A mismatch stops the update before downtime. For a reviewed migration, stop all services,
back up the database and executor state, prepare the target dependencies in the printed staging
directory, and apply that directory's Alembic configuration with migration credentials. Apply its
grants too. Keep services stopped until the matching source is activated; an older release may not
work with the migrated database. This updater never performs a schema migration or rollback.

After confirmation, update stops the services and saves the previous source, ignored dependencies,
and web build under `/var/lib/nachtlabs-maintenance/update.*` with root-only access. It then
fast-forwards the installed branch, syncs dependencies in place, copies the prepared bundle and
static assets, checks the database revision again, starts the services and health-checks them.
Allow disk space for both a staged release and a complete recovery copy.

An interrupted activation leaves `/var/lib/nachtlabs-maintenance/update-pending`. Updates and resets
refuse to proceed while this marker exists. Recover from its saved script, which does not depend
on the partially installed Python environment:

    sudo bash /var/lib/nachtlabs-maintenance/update-pending/recover-update.sh

Recovery stops services, restores the previous tracked source and runtime files, verifies that the
database still matches the restored release, and restarts only the services that were previously
active. It also handles interruption before the recovery archive was completed, when activation had
not begun. Do not edit the installation while recovery is pending: recovery deliberately restores
the source and runtime from the admitted clean checkout. If the database changed meanwhile,
recovery refuses to restart an incompatible release. After a host restart, inspect this marker and
recover before manually starting services. Recovery does not revert database data or executor state.

Successful update or recovery removes the pending marker but retains the protected recovery copy
and preparation directory for inspection. Retire those printed directories only after validating the
installation and confirming no pending recovery refers to them.

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
