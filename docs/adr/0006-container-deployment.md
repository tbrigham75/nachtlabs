# ADR 0006: containers for the control plane, native systemd for the executor

Date: 2026-09-28. Supersedes the "no containers in version one" constraint in `Original Prompt` §7 and in `NachtLabs-Implementation-Plan.md:120`, by owner decision.

## Why this changed

The version-one constraint was a workplace restriction, not a technical judgement: authoring
happened on Windows under a policy that forbade container runtimes. That constraint no longer
applies. Containers are now permitted for the control plane, and the deployment target is a
server the operator administers directly.

## Decision

Deployment splits into three tiers, and the split follows the security model rather than
convenience.

| Tier | Components | Deployment | Reason |
|---|---|---|---|
| 1 | API, worker, interface, PostgreSQL | Containers (`compose.yaml`) | Reproducible, disposable, and it makes the integration suite runnable |
| 2 | Build toolchain (Node 24, Python 3.12, uv, pnpm 10) | Container build stages | Matches the pinned-versions discipline already required by `package.json` engines |
| 3 | Executor broker and its job sandboxes | **Native systemd only** | Its isolation cannot be reproduced in a container |

The native systemd path in `scripts/install-systemd.sh` and `systemd/` remains supported. This
is an addition, not a replacement: an operator who prefers to run four systemd units on a host
they administer is not required to use containers.

## Why the executor stays native

`packages/core/src/nachtlabs/execution/sandbox.py:83-126` builds one transient systemd unit per
job, and the properties that make an untrusted job safe are host-level:

- `DynamicUser` — a per-job system identity
- `RootDirectory` — a curated root assembled per release, not a build-time image
- `ProtectSystem=strict`, `RestrictNamespaces`, `ProcSubset=pid` — namespace restrictions
- `IPAddressAllow` / `IPAddressDeny` — **cgroup-v2 BPF programs** attached to the job's cgroup

Docker has no equivalent for the first three, and the fourth is not expressible at all: network
egress control in a container is a proxy or firewall concern, not a property of the job's cgroup.
A containerized executor would therefore be **strictly less isolated** than the native one.

This is not only a theoretical difference. `docs/operations/executor-qualification.md:14` requires
observing that "cgroup/BPF IP filtering works on this host, including IPv6; missing enforcement
blocks qualification." That row is unsatisfiable inside a container, so a containerized executor
could never be honestly qualified.

`nachtlabs-executor.service` also shares the host mount namespace on purpose so jobs see the
broker's bounded tmpfs workspaces, and documents that adding mount-namespace hardening would break
that handoff. A container boundary sits directly on top of it.

## What the container path does not change

No security control is relaxed by running in a container. Verified against the source:

- **Origin/CSRF.** `origin_permitted()` (`apps/api/src/nachtlabs_api/dependencies.py:35-46`) is
  an exact per-request membership test against `Settings.permitted_origins`. The origin is still
  operator-supplied and still exact. `ALLOWED_HOSTS` cannot use a wildcard: the validator
  (`settings.py:72-79`) tests exact membership, so `*` refuses to start rather than widening it.
- **Least privilege.** `scripts/grants.sql` is applied unchanged to both databases, and the
  runtime roles are the same four.
- **Immutable evidence.** Unchanged; `audit_events` still has no UPDATE/DELETE/TRUNCATE for any
  application role.
- **Egress.** `NACHTLABS_INTEGRATION_NETWORK_ENABLED` and
  `NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE` still default to false. `container-init.py` writes
  them as false and will not turn either on; the operator opts in.
- **First-run.** `POST /auth/setup` is still unauthenticated until an Owner exists, so
  `NACHTLABS_SETUP_TOKEN_REQUIRED` remains the switch that matters on a reachable network.

## One deliberate difference

`scripts/configure.py` refuses a plain-HTTP origin for anything but loopback. That restriction
belongs to the systemd install path, where the operator is at a console. The container path
derives the origin from `NACHTLABS_LAN_ORIGIN` and accepts an HTTP LAN address, which sets
`NACHTLABS_ENV=development`. That has exactly two costs, both stated in
`docs/operations/container-deployment.md`: the session cookie loses its `Secure` attribute, and
the synthetic `DevelopmentAdapter` fixture becomes reachable. It is not a bypass — it is a
different, narrower deployment target.

## Consequences

- The origin cannot be configured from the browser. It is a deployment input, because the CSRF
  origin check runs before any page renders. Making it web-configurable would mean moving a
  security control to the database, which is deferred to its own change and its own review.
- Integration tests can be run without publishing a database port, because they run on the
  compose network as a one-shot container.
- Executor qualification remains a native-host activity. Nothing in this ADR makes it otherwise.
