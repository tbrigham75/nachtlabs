# Executor qualification runbook

Two supported paths exist:

- **Container path** (ADR 0007, current release target `openclaw01`): the executor
  broker runs in a container with four operator-mandated compensating controls.
  This is the **primary path** on a host that does not have a qualifying
  native-systemd setup.
- **Native path** (ADR 0006, still supported and the strictest): the executor
  broker is a systemd unit on a disposable Ubuntu 24.04 host, and per-job work
  runs in `DynamicUser` units with `RootDirectory` and cgroup/BPF egress.

Which path you can use depends on what the host can actually enforce. Read the
*qualify for what you can observe* section below before choosing. Do **not**
record a container path as a pass for a row the container path does not
enforce; that is the single most common mistake in qualification.

The shared procedure for both paths is in
[executor-qualification.md](executor-qualification.md). That file says *what*
must be observed; this file says *how to get there* and *what the container path
can and cannot substitute for*.

Never use live credentials as canaries. Never put a real host secret in a
workspace to test denial.

---

## Container path (ADR 0007)

### 0. Before you start

```bash
docker --version
docker compose version
docker info | grep -E 'Security|Name'
# Record host kernel. The container escape model depends on it.
uname -a
```

The container path's guarantee is the *broker boundary*: who can enqueue work,
what the loop can read, and what it can reach on the network. It is **not** a
guarantee about the isolation of the untrusted commands the broker dispatches —
those still need a host that can enforce them (see § "container path cannot
substitute" below).

### 1. Build the broker image

The image's last build stage is `test` (a dev-only stage). Building without a
target tags the wrong artifact. The compose overlay names the target
explicitly; the standalone `docker build` command must too.

```bash
cd /opt/nachtlabs
docker build --target final -t nachtlabs/executor:local -f Dockerfile.api .
docker images nachtlabs/executor:local
```

If you see `psql: command not found` later in the pipeline, the target was
not honored. Re-run with an explicit `--target`.

### 2. Install the control plane (if not already up)

```bash
sudo python3 scripts/container-init.py --origin https://your-host
docker compose up -d --build
docker compose ps
```

`container-init.py` now additionally generates
`/etc/nachtlabs/credentials/executor-channel-key` (base64, 32 random bytes,
mode 0600) **before** the first `worker.env`/`executor.env` write. Inspect
it once to confirm the mode and ownership:

```bash
sudo ls -l /etc/nachtlabs/credentials/executor-channel-key
# expected: -rw-------  1 root root  44 ...
sudo python3 - <<'PY'
import base64
data = open("/etc/nachtlabs/credentials/executor-channel-key","rb").read()
raw = base64.b64decode(data)
assert len(raw) == 32, f"channel key is {len(raw)} bytes, not 32"
print("channel key: ok, 32 bytes after base64")
PY
```

### 3. Bring up the broker overlay

This is the command the deployment lane will use. It does **not** modify the
existing services in `compose.yaml`; it adds the `executor` service defined in
`compose.executor.yaml`.

```bash
docker compose -f compose.yaml -f compose.executor.yaml up -d --build executor
docker compose -f compose.yaml -f compose.executor.yaml ps executor
docker logs nachtlabs-executor 2>&1 | tail -50
```

### 4. Check the four compensating controls

These are the observations the container path actually substitutes for, and each
is observable from the deployment host by command.

**Control 1 — Authenticated channel.**

```
(a) The key is generated and 0600:        see § 2 above
(b) The broker verifies:                  broker.py `context_for` requires
                                          `executor_verify_spec(...)` on
                                          claim. A forger who inserted a job
                                          row without a valid signature is
                                          rejected. Verify the code path by
                                          reading, and by negative test:
docker compose -f compose.yaml -f compose.executor.yaml run --rm executor \
  python3 - <<'PY'
  # From inside the executor container, sign with the real key using the
  # real spec serialization; then corrupt one field and show the signature
  # no longer verifies. Do not run a real agent or job here.
  import json, os
  from nachtlabs.security import executor_sign, executor_verify
  key = open(os.environ["NACHTLABS_EXECUTOR_CHANNEL_KEY_FILE"], "rb").read()
  spec = {"project_id": "a"*36, "run_id": "b"*36, "spec_hash": "c"*64,
          "stage": 1, "attempt": 1, "specification": {}}
  sig = executor_sign(spec, key)
  assert executor_verify(spec, sig, key), "verify should succeed"
  spec2 = dict(spec); spec2["stage"] = 2
  assert not executor_verify(spec2, sig, key), "verify must reject a tampered spec"
  print("control-1 (HMAC sign/verify): ok")
  PY
```

**Control 2 — Least-privilege identity.**

```bash
docker inspect nachtlabs-executor \
  --format '{"User":.Config.User,"CapDrop":.HostConfig.CapDrop,"NoNewPrivs":.HostConfig.NoNewPrivileges,"ReadOnly":.HostConfig.ReadOnly,"MemoryLimit":.HostConfig.Memory,"CPUShares":.HostConfig.CpuShares,"PidsLimit":.HostConfig.PidsLimit}'
docker compose -f compose.yaml -f compose.executor.yaml exec executor id
# expected: uid=9000(nachtlabs) gid=9000(nachtlabs) groups=9000(nachtlabs)
```

**Control 3 — Network segregation.**

The overlay defines no `ports:` block for the executor and joins only the
`backend` bridge. Verify:

```bash
docker compose -f compose.yaml -f compose.executor.yaml port executor
# expected: (empty — no published ports)
docker compose -f compose.yaml -f compose.executor.yaml exec executor \
  getent hosts postgres
# expected: resolves
docker compose -f compose.yaml -f compose.executor.yaml exec executor \
  python3 -c "import socket; socket.setdefaulttimeout(2); socket.create_connection(('8.8.8.8', 53), 2)" 2>&1
# expected: OSError / timeout. The container has no default route.
# If this SUCCEEDS, the host or overlay granted egress that ADR 0007 does
# not allow. Record and do not pass control 3.
```

**Control 4 — Credential isolation.**

The HMAC key is written by container-init.py, not baked into an image layer.
The broker image is built from the `final` stage; nothing in the image layers
contains the key. Verify by scanning the image:

```bash
docker save nachtlabs/executor:local | tar -xO --to-stdout 2>/dev/null | head -c 0 \
  ; docker history nachtlabs/executor:local | tail
# The history should not contain a line mentioning "executor-channel-key".
# A byte scan would also work but is not a required observation.
docker compose -f compose.yaml -f compose.executor.yaml exec executor \
  sh -c 'ls -l /etc/nachtlabs/credentials/executor-channel-key'
# expected: -rw------- (from the read-only mount of the config volume)
```

### 5. What the container path does *not* observe

These rows from `executor-qualification.md` are **NOT RUN** under the
container path, and the runbook does not pretend otherwise. Do not record a
pass.

| Qualification row | Container path status | Reason |
|---|---|---|
| Row 1 — `RootDirectory` exposes only curated tools and a single `/work` | **NOT RUN** | The container path does not curate a per-job root. Job isolation still needs the host. |
| Row 2 — Dynamic identities cannot read API/worker keys | **NOT RUN** as a *job* guarantee | The container path satisfies it for the *broker process* (least-priv user, 0600 key). It does not say anything about the untrusted job that the broker dispatches. |
| Row 3 — Nested commands inherit no-new-privileges / namespace / cgroup limits | **NOT RUN** | `sandbox.py` runs `/usr/bin/systemd-run` per job. In the container path that binary is not present and the container's `security_opt` does **not** apply to dispatched child processes. |
| Row 4 — Network-disabled commands cannot connect or resolve | **NOT RUN** | Same reason: egress for dispatched jobs is a host firewall / cgroup BPF concern, and the container path does not provide it. |
| Row 5 — cgroup/BPF IP filtering works, including IPv6 | **NOT RUN** | The container has no BPF program attached to the dispatched job because the dispatched job does not run in a container with a cgroup. |
| Row 6 — Cancellation kills grandchildren and leaves no active cgroup | **NOT RUN** | The broker's `stop.wait(5)` covers the broker's own Python process. It does not kill an in-flight dispatched job running under `systemd-run` on the host. |
| Row 7 — Broker death / restart stops recorded unit and releases orphan tmpfs | **NOT RUN** | The broker does manage its own state under `/var/lib/nachtlabs/executor` via `files.py`. It does **not** clean up host cgroups or tmpfs workspaces that a previous host-path run left behind. |
| Rows 8–13 (runaway limits, symlink/hardlink/device rejection, protected-input separation, pinned agent versions, verifier separability, missing-scan/Journey/changed-catalog blocks) | **NOT RUN** | Not substituted by any of controls 1–4. These are code properties and must be verified by their own tests on whatever path runs the broker. |
| Row 14 — Two broker processes cannot execute concurrently and lease ownership cannot be stolen | **PARTIALLY RUN** | The broker takes its advisory lock over the DB connection, which both paths share. You can demonstrate two broker processes on the container path race and only one wins. The `systemd-run` single-instance property is not exercised. Record what you observed and leave the native rows unmarked. |
| Row 15 (final: receipt binding) | **APPLIES** | The receipt binding and catalog-hash attestation are path-agnostic; do them the same way on both paths. |

### 6. What the container path does NOT grant

- **It does not allow provider delivery.** Organization policy blocks
  remote-git-based delivery. Any row that requires observing a real agent
  delivering a candidate to a real repository is **NOT RUN** on both paths.
  The synthetic fixture (`demo/checks/development_agent.py`) never certifies
  a real provider; a pass with the fixture is not a pass for the provider.
- **It does not curate `RootDirectory`.** The per-job curated root is a
  host property (`sandbox.py`: `runtime_root` must be root-owned, no
  group/world write, digested into the catalog). Containers do not substitute.
- **It does not provide BPF IP filtering for dispatched work.** cgroup-v2
  BPF egress for dispatched jobs is a host property. The container's
  "no default route" is a *default-deny on the broker's own socket*.

### 7. Record the container-path receipt

The native `qualify-executor.py` script is the attestation tool. For the
container path, record the same evidence file the native path would produce,
then call the same script with a note flagging the path:

```bash
# evidence.md should list: every control observation in § 4, every NOT RUN
# row from § 5 with its reason, the host facts from § 0, the image digest,
# and the catalog hash.
sudo python3 scripts/qualify-executor.py \
  --evidence /path/to/container-path-evidence.md \
  --confirm-linux-isolation-passed \
  --notes "container path; not a host-path attestation; see ADR 0007"
```

If `qualify-executor.py` does not accept `--notes` today, add the note to
the evidence file instead and do not run the `--confirm...` flag on a partial
qualification. Only run it when the evidence file explicitly says
"not a full host-path attestation; partial, container-path receipt".

---

## Native path (unchanged from ADR 0006 era)

> Sections 0–8 of the native path (previously sections 0–7 of this file) are
> reproduced from the earlier revision for operators still running the native
> broker. They remain valid and are not superseded by ADR 0007.

*(See git history; the native-path commands are unchanged: `install-systemd.sh`,
`scripts/configure.py`, runtime root curation, local mirror, catalog, the 15-row
table, `qualify-executor.py`, `systemctl enable --now nachtlabs-executor`,
`reconcile-executor.py`, rollback.)*

**A pass is a pass on the path you ran.** A container-path receipt does not
cover the native-path rows, and vice versa. If you run both, record two
receipts.

---

## Source-check evidence (recorded with the real output of the day)

Commands and observed results on 2026-09-30 on `openclaw01`, repo
`/home/tom/projects/web-app/nachtlabs` (packages/core / apps/worker / tests).

```
uv run --no-sync ruff check packages/core apps/api apps/worker tests scripts
  → All checks passed!
uv run --no-sync ruff format --check packages/core apps/api apps/worker tests scripts
  → 89 files already formatted
uv run --no-sync mypy
  → Success: no issues found in 56 source files
uv run --no-sync pytest -q
  → 124 passed, 82 skipped, 5 warnings in 14.89s
uv run --no-sync pytest -q tests/test_container_init.py
  → 24 passed  (contains test_no_compose_environment_shadows_a_generated_key,
                test_services_build_the_final_stage, and the executor_env
                generation assertions — all exercised against my change)
pnpm --ignore-scripts lint
  → 0 errors, 1 warning (pre-existing: "Unused eslint-disable directive" in
    packages/mcp-server/tests/live.test.ts; not introduced by this change)
docker compose -f compose.yaml -f compose.executor.yaml config --quiet
  → OK
docker build --target final -t nachtlabs/executor:local -f Dockerfile.api .
  → BUILD_EXIT=0, named to docker.io/nachtlabs/executor:local
```
