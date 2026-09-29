# Working agreement

Source authoring and execution now happen on Linux. Earlier agreements that required
authoring through Windows PowerShell and blocked WSL no longer describe the working
environment; see [linux-verification-2026-09-28.md](planning/linux-verification-2026-09-28.md)
for the environment actually used and the limits it places on the evidence.

No remote Git/plugin/CLI/API workaround, fetch/pull/push, remote PR or CI. Local commits
need explicit instruction.

Source checks are expected to pass before a change is considered complete. `make lint`,
`make typecheck`, `make format-check`, `make build` and `make test` run without root and
without a database, and must be run rather than assumed. `make test` covers the unit and
native suites; the integration suite runs as a one-shot container on the compose network
(see [container deployment](operations/container-deployment.md)), while the E2E, migration
and scan targets need infrastructure the authoring host does not have and are reported as
NOT RUN with the reason stated.

The control plane may be deployed from `compose.yaml`, and the executor must not be
(containerless isolation primitives — ADR 0006). Changes to either path keep the existing
guarantees: the origin check stays an exact per-request membership test, `scripts/grants.sql`
stays the least-privilege statement set, the network switches stay off by default, and the
executor stays a native systemd service.

Authoring and verification currently run under WSL2. That is good enough for source
correctness and useless for deployment evidence: systemd unit behavior, DynamicUser
isolation, cgroup limits, the privileged broker boundary, executor qualification,
backup/restore and key rotation require a real Ubuntu 24.04 host. Do not report a WSL2
result as a native Linux one.

Keep public schemas distinct from persistence; enforce scopes/project membership before
reads; never log credentials/bodies/holdouts/raw external errors. Add migrations and
relevant tests/docs when behavior changes. Separate claims from evidence: a passing check
is recorded with the command that produced it, and everything not run stays labelled NOT
RUN. Do not invent locks, coverage, screenshots or readiness.
