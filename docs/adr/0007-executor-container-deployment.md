# ADR 0007: the executor is containerized, with compensating controls

Date: 2026-09-30. Status: ACCEPTED. Supersedes ADR 0006 (container deployment for the
control plane, native systemd for the executor).

## Decision

The entire stack — API, worker, web, PostgreSQL, and the **executor broker** — runs in
containers. ADR 0006's third tier ("executor is native systemd only, its isolation cannot
be reproduced in a container") is withdrawn by operator decision.

## Why this changed

ADR 0006 recorded the split by the security model. Since then two facts have changed:

1. **The operator's environment.** Work-environment policy blocked container runtimes
   (and WSL2). The release target `openclaw01` (Ubuntu 24.04, Docker) is a single
   host the operator administers directly, and the operator's stated path is 100% Docker.
   Maintaining two deployment shapes (native systemd for the executor + containers for
   the control plane) costs more operational surface than the isolation difference
   buys, on this host.
2. **The broker boundary was never the only trust boundary.** ADR 0006's strongest
   argument was `DynamicUser`/`RootDirectory`/BPF egress for *jobs*. That argument
   still holds — and is honored: **jobs run where a host can enforce them**. But the
   *broker itself* (the small root loop that signs, claims, hashes, dispatches) is a
   trusted component, and trusted components can be confined by a different, coarser
   contract: authenticated channel, least-privilege identity, network segregation,
   credential isolation. The four controls below are that contract.

## Compensating controls (operator-mandated, non-negotiable)

| # | Control | Where it is enforced | Runbook concern answered |
|---|---|---|---|
| 1 | **Authenticated worker→executor channel.** Worker signs each `ExecutorJob`'s spec with an HMAC-SHA256 key (`security.executor_sign_spec`); the broker rejects unsigned or mismatched rows (`executor_verify_spec`) at claim time. `channel_signature` is excluded from both the signature body and the spec fingerprint, so the two checks do not depend on each other. No plaintext credentials on the wire: the channel key never leaves `/etc/nachtlabs/credentials` and the database transport is the TLS-postgres socket the stack already uses. | `packages/core/src/nachtlabs/security.py`, `workflows/engine.py`, `execution/broker.py` | "Broker boundary" (executor-qualification.md rows 1, 2, 14): a forger who can reach the database row table cannot mint a valid spec. |
| 2 | **Least-privilege in-container identity/broker.** The broker image runs as the `nachtlabs` user (uid/gid 9000, `nologin`) — no root. Compose pins `cap_drop: [ALL]`, `security_opt: [no-new-privileges]`, a bounded `mem_limit`/`cpus`/`pids_limit` (the container-runtime counterparts of the unit's `MemoryMax`/`TasksMax`), and a read-only root filesystem where the broker does not need to write. | `Dockerfile.api` (final stage), `compose.executor.yaml` | "Nested commands inherit no-new-privileges, namespace/capability restrictions and cgroup limits" (row 3), "runaway memory/processes … terminate within limits" (row 7). |
| 3 | **Network segregation.** The executor service has no `ports:`, joins only the internal `backend` bridge (no published listener), and may only reach `postgres` by DNS name on that segment. Host LAN / Docker default network are unreachable by design (no `network_mode: host`, no extra bridge, no `extra_hosts` pointing at LAN ranges). Egress outside the segment is *not* granted by the broker container at all — provider egress, when a job needs it, is handled per job (see row on egress below), never by opening the broker to the internet. | `compose.executor.yaml` (`networks`, absence of `ports`) | "Network-disabled commands cannot connect or resolve destinations; permitted jobs reach only pinned approved addresses" (row 4). The broker itself needs no outbound egress and is given none. |
| 4 | **Credential isolation.** The HMAC channel key (32 random bytes, base64) is generated at install time by `scripts/container-init.py`, written to the `config` volume as `credentials/executor-channel-key` (mode 0600), and bound-mounted read-only into the broker. **It is never baked into an image layer.** The broker's database credential is a dedicated `nachtlabs_executor` role whose grant set is the least-privilege one in `scripts/grants.sql` (owned by the deployment lane — this ADR does not change it; if a new role/statement is needed, request one). | `scripts/container-init.py`, `compose.executor.yaml` (volume binding, `user`) | "Dynamic identities cannot read API/worker keys, host homes, broker state" (row 2): the key exists in exactly one place, is not in the image, and the broker has no host filesystem to wander into. |

## What is *not* solved by containers (stated honestly)

ADR 0006 was right about one thing and we keep its conclusion: **per-job isolation still
needs a host that can enforce it.** `sandbox.py` launches jobs through
`/usr/bin/systemd-run` with `DynamicUser`, `RootDirectory`, and cgroup/BPF egress.
That path runs on a host where systemd is the job supervisor — today, the native
deployment. The container decision in this ADR covers the **broker boundary** (who may
enqueue work, how the loop is confined, what it can read and say). It does *not*
claim to replace job-level isolation. The qualification runbook
(`executor-qualification-runbook.md`) records exactly which rows are satisfied by the
container path, which rows are satisfied by the host path, and which rows are NOT RUN
because the org blocks remote git and real provider delivery.

## Residual risks (accepted)

- **Shared host kernel.** A container escape is still a compromise of the host. The
  controls above narrow the broker's surface (no root, no caps, no egress, no baked
  secrets) but do not eliminate a kernel exploit. The operator accepts this for the
  single-host release target.
- **Single key in the config volume.** Losing the `config` volume loses the channel key
  and invalidates in-flight job rows. Backup-and-restore covers this as it does the
  master key.
- **Broker trust still lives in code.** A malicious broker process can do what a
  non-privileged user with a scoped DB role and no network can do — which is less than
  root on the host, not zero.
- **Native-path runbook still exists.** Operators who deploy executor natively continue
  to follow `systemd/nachtlabs-executor.service` + `executor-qualification.md` (native
  section of the runbook). This ADR does not delete it.

## Affected files

- `scripts/container-init.py` — generates the channel key and writes
  `NACHTLABS_EXECUTOR_CHANNEL_KEY_FILE` into `worker.env` and `executor.env`.
- `packages/core/src/nachtlabs/security.py` — `executor_sign` / `executor_verify` /
  `executor_sign_spec` / `executor_verify_spec` (HMAC-SHA256 over a stable
  serialization of the spec minus its own signature).
- `packages/core/src/nachtlabs/settings.py` — `executor_channel_key_file` setting.
- `packages/core/src/nachtlabs/workflows/engine.py` — signs the spec before enqueue.
- `packages/core/src/nachtlabs/execution/broker.py` — verifies the signature at claim.
- `compose.executor.yaml` — the executor service (this ADR's shape).
- `docs/operations/executor-qualification-runbook.md` — container-path section.

## ADR 0006 status

ADR 0006 is **SUPERSEDED**. Its control-plane decisions (tiers 1 and 2) stand. Its
tier-3 "executor is native systemd only" is lifted by this ADR. Operators following
ADR 0006 who deployed the executor natively do not need to migrate; this ADR is an
addition, and the native path remains supported.
