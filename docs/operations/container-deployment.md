# Container deployment

The control plane runs from `compose.yaml`. The executor does not, and cannot; see
[ADR 0006](../adr/0006-container-deployment.md) and
[executor qualification](executor-qualification.md).

## Requirements

- Docker Engine with Compose v2 (`docker compose version`)
- 1 GiB free for images, 2 GiB for the database volume
- The documented toolchain is **not** needed on the host. The images pin Node 24, Python 3.12,
  uv 0.12 and pnpm 10.

## First start

The only input is the origin, because the application cannot know the address a browser will use
to reach it:

```bash
git clone git@github.com:tbrigham75/nachtlabs.git
cd nachtlabs
NACHTLABS_LAN_ORIGIN=http://<your-server-ip>:3035 docker compose up -d
```

Then read what the stack decided:

```bash
docker compose logs init
```

It prints the URL to open and confirms the generated credentials. There is nothing to edit: the
master key, the one-time setup token and one database credential per role are generated into the
config volume on first start and never enter the repository or an image layer.

Open the URL. The first account you create becomes the Owner and setup closes permanently.

| Service | Role |
|---|---|
| `init` | Generates credentials and derives the origin. Idempotent; never overwrites. |
| `postgres` | PostgreSQL 16. Not published to the host. |
| `roles` | Creates the four runtime roles and the `_test` database. |
| `migrate` | Applies Alembic to the application database. |
| `schematest` | Applies the same migrations to `nachtlabs_test`. |
| `grants` | Applies `scripts/grants.sql` to both databases. |
| `api`, `worker`, `web` | The services. Only `web` publishes a port (3035). |

Startup order is enforced with `depends_on` conditions, so a service never starts against a
database that has not been migrated and granted.

## LAN without TLS

A plain-HTTP origin sets `NACHTLABS_ENV=development`, because production mode refuses any origin
that is not HTTPS (`packages/core/src/nachtlabs/settings.py:59-66`). That is a real relaxation and
it costs two things:

- **The session cookie is not marked `Secure`.** `secure_cookies` is true only when every
  permitted origin is HTTPS, so on HTTP the cookie travels in cleartext. On a trusted home LAN
  this is a small exposure; it is not one to accept on a shared or untrusted network.
- **The synthetic `DevelopmentAdapter` becomes reachable** (`integrations/development.py:11`). It
  is a fixture that writes a greeting file, not a coding agent, and it is not registered as a
  production provider — but the code path exists in this mode and not in production mode.

If you later put a certificate in front of this, set `NACHTLABS_LAN_ORIGIN=https://...`. The
generator then writes `NACHTLABS_ENV=production`, the HTTPS origin check applies, and the cookie
regains `Secure`.

### First-run security

`POST /auth/setup` is unauthenticated until an Owner exists, so **whoever reaches the URL first
becomes the Owner**. On a network you do not trust, set the token requirement before starting:

```bash
NACHTLABS_SETUP_TOKEN_REQUIRED=true NACHTLABS_LAN_ORIGIN=... docker compose up -d
```

Read the token with `docker compose exec api cat /etc/nachtlabs/credentials/bootstrap-token`.

## Connecting a model provider

Provider egress is off by default and this file never enables it on its own. It is recorded in the
generated configuration by `init`, which is the only place the value is read from.

**On a new installation**, pass the switches when the stack is first started:

```bash
NACHTLABS_INTEGRATION_NETWORK_ENABLED=true \
NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true \
NACHTLABS_LAN_ORIGIN=http://<server-ip>:3035 \
docker compose up -d
```

**On an installation that already started**, the generated files are never overwritten, so a
restart will not pick the value up. Apply it to what is already there:

```bash
NACHTLABS_INTEGRATION_NETWORK_ENABLED=true \
NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true \
NACHTLABS_REWRITE_CONFIG=true \
docker compose run --rm init
docker compose restart api worker
```

`NACHTLABS_REWRITE_CONFIG=true` updates only the three egress switches
(`INTEGRATION_NETWORK_ENABLED`, `INTEGRATION_ALLOW_HTTP_PRIVATE`,
`GIT_PROVIDER_NETWORK_ENABLED`). Credentials, the master key, tokens and database URLs are not
reachable from it. It is a separate step rather than automatic so that restarting the stack stays a
no-op, and so that widening what an installation may reach is always a deliberate act.

The restart matters: these values are read when a process starts, so `api` and `worker` keep the
old value until they are restarted.

- `INTEGRATION_NETWORK_ENABLED` permits provider calls at all. Both the API and the worker must
  agree: the worker is the process that dials the provider, and a mismatch means discovery and
  planning behave differently.
- `INTEGRATION_ALLOW_HTTP_PRIVATE` additionally permits cleartext to a non-loopback private
  address. A loopback endpoint does not need it; a LAN address does. The cost is stated in
  `.env.example` and in the wizard: the work request, Mission, Journeys, allowed paths, validation
  commands and repository metadata travel in the clear, and the reply becomes the recorded plan
  for a governed run.

### Why compose `environment:` is not how these are set

`with-env.sh` sources the generated file *after* compose has set the container's environment, so
any value passed in the compose `environment:` block for a key that also appears in the generated
file is silently discarded. That made an earlier version of this section wrong: it documented a
`docker compose up -d` with the switch set, which could not work, and the wizard told the operator
to edit a file inside a named volume that the host cannot see. The switches are absent from the
`environment:` block on purpose, and a test asserts they stay absent.

Then use the setup wizard in the interface: origin, pinned numeric IP, and both permission
toggles. The address is stored in the database and never written to a file in the repository.

## Running the checks

```bash
make lint
make typecheck
make format-check
make build
```

The integration suite runs as a one-shot container on the compose network, so no database port is
published purely for a test run:

```bash
docker build --target test -f Dockerfile.api -t nachtlabs/test:local .
docker run --rm --network nachtlabs_backend \
  -v nachtlabs_config:/etc/nachtlabs:ro \
  -e NACHTLABS_TEST_DATABASE_URL_FILE=/etc/nachtlabs/credentials/test-db \
  -w /opt/nachtlabs -e 'PATH=/tmp/testenv/bin:/usr/local/bin:/usr/bin:/bin' \
  nachtlabs/test:local pytest -m integration -q
```

`tests/conftest.py` refuses any database whose name does not end in `_test`, and the test database
additionally carries a `TRUNCATE` grant for `nachtlabs_api` that the application database does not
have. The application role must never hold it: `TRUNCATE` is how the least-privilege model proves
the API cannot remove audit history wholesale.

## Operating

```bash
docker compose ps
docker compose logs -f api worker
docker compose restart api          # a config change needs a restart, not a reload
docker compose down                 # stop, keep data
docker compose down -v              # stop and delete the master key; stored secrets become unreadable
```

**Back up the `config` volume.** It holds the master key, and without it every encrypted value in
the database is unreadable:

```bash
docker run --rm -v nachtlabs_config:/config -v "$PWD":/backup alpine \
  tar czf /backup/nachtlabs-config.tar.gz -C /config .
```

Restarting the stack is safe and changes nothing: `init` never overwrites an existing file.

## Changing the origin

The origin is written once, at first start, and `init` does not overwrite it. To change it:

```bash
docker compose down
docker volume rm nachtlabs_config      # destroys the master key; only for a fresh install
NACHTLABS_LAN_ORIGIN=http://<new-ip>:3035 docker compose up -d
```

For an existing installation, edit the generated `api.env`, `worker.env`, `executor.env` and
`migration.env` inside the volume instead, so the credentials survive.

## What is not in this file

The executor. Not as an oversight — `DynamicUser`, `RootDirectory` and cgroup-v2 BPF
`IPAddressAllow` have no container equivalent, so a containerized executor would be less isolated
and its qualification unsatisfiable. Run it natively on the host.
