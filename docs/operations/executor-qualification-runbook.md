# Executor qualification runbook

The procedure is in [executor-qualification.md](executor-qualification.md). This is the
ordered, command-level runbook for performing it. Read both: the procedure says *what* must
be observed, this says *how* to get there without guessing.

**This cannot be done on WSL2, in a container, or on a shared host.** It needs a disposable
Ubuntu 24.04 machine you administer. `scripts/qualify-executor.py` records *your* judgement
under `--confirm-linux-isolation-passed`, and a receipt signed on a platform that cannot
enforce the isolation is a false claim about your own system's security. See
[ADR 0006](../adr/0006-container-deployment.md) for why this cannot be containerized.

Never use live credentials as canaries, and never put a real host secret in `/work` to test
denial.

## 0. Before you start

```bash
# A dedicated host, not a laptop and not production.
hostnamectl                       # record the kernel and OS for the report
systemd --version
cat /sys/fs/cgroup/cgroup.controllers    # needs cgroup2; 'bpffs' is the one that matters
mount | grep bpffs || echo "NOT MOUNTED"
systemd-analyze features | grep -i bpf
```

If `bpffs` is not mounted, or systemd reports no BPF support, **stop**. Row 14 of the
qualification table is unsatisfiable and the answer is a failed qualification, not a
warning. Record that and do not issue a receipt.

## 1. Install the control plane

The executor is a separate trust boundary and is not part of `compose.yaml`. Install the
native units:

```bash
cd /opt/nachtlabs
sudo bash scripts/install-systemd.sh
sudo python3 scripts/configure.py --origin https://your-host
sudo make migrate
sudo -u postgres psql -f scripts/grants.sql          # against the named database
sudo systemctl enable --now nachtlabs-api nachtlabs-worker nachtlabs-web
make healthcheck
```

`install-systemd.sh` installs the executor unit but does **not** start it, and
`nachtlabs-executor.service` carries `ConditionPathExists=/etc/nachtlabs/executor-qualification.json`,
so it will not start before qualification regardless. Verify:

```bash
systemctl status nachtlabs-executor     # expect: inactive, and the condition named
```

Create the first account through the browser. You need a working control plane before
exercising the executor.

## 2. Build the curated runtime

`runtime_root` is mounted as `RootDirectory` for every job, so it must be a root-owned,
group/world-unwritable directory containing only what jobs are allowed to see. The code
checks all three properties on every load (`sandbox.py:69-79`).

```bash
sudo install -d -o root -g root -m 0755 /opt/nachtlabs-runtime
sudo install -d -o root -g root -m 0755 /opt/nachtlabs-runtime/checks

# The agent CLI. Exactly one, pinned. For a first pass use the synthetic fixture
# (see step 2b) rather than a real coding agent.
sudo install -o root -g root -m 0755 /path/to/agent /opt/nachtlabs-runtime/agent

# Tools a job is allowed to execute. A minimal set is the point.
sudo install -o root -g root -m 0755 /usr/bin/python3 /opt/nachtlabs-runtime/python3
```

The real Python is a symlink on most distributions. `RootDirectory` does not follow
symlinks out of the curated root, so copy the resolved binary and its shared libraries, or
accept that `/usr/bin/python3` is unavailable inside a job.

### 2b. The synthetic fixture

`demo/checks/development_agent.py` is not an agent. It writes one file and reports a verdict,
and it exists to prove the plumbing — catalog validation, sandbox launch, tmpfs workspace,
candidate snapshot, digest verification, the verifier stage — without depending on a real
agent's safety. Use it first. Qualify the real agent separately, and never let a pass with
the fixture be described as a pass for the agent.

```bash
sudo install -d -o root -g root -m 0755 /opt/nachtlabs-runtime/checks
sudo install -o root -g root -m 0644 demo/checks/development_agent.py \
  /opt/nachtlabs-runtime/checks/development_agent.py
```

## 3. Create a local mirror

The catalog names a repository by a local bare mirror. Remote Git is out of scope; this uses
local Git only.

```bash
sudo install -d -o root -g root -m 0700 /var/lib/nachtlabs-executor/mirrors
git init --bare /var/lib/nachtlabs-executor/mirrors/demo.git
git -C demo/repository push /var/lib/nachtlabs-executor/mirrors/demo.git HEAD:main
```

## 4. Write the catalog

Copy the example and fill it in. The code is the authority; the fields it rejects are listed
with their error codes so a refusal tells you which property was wrong.

```bash
sudo install -d -o root -g root -m 0750 /etc/nachtlabs
sudo install -o root -g root -m 0600 config/execution-catalog.example.json \
  /etc/nachtlabs/execution-catalog.json
sudoedit /etc/nachtlabs/execution-catalog.json
```

| Field | Requirement | Failure code |
|---|---|---|
| `schema` | exactly `1` | `catalog_schema` |
| `runtime_root` | absolute, existing, root-owned, no group/world write, not a symlink | `runtime_root` |
| `allowed_addresses` | every entry: not metadata, loopback, link-local, reserved, multicast or unspecified; globally routable **unless** `allow_private_network` | `executor_network_policy` |
| `allow_private_network` | `true` **only** for a dedicated private model address | `executor_network_policy` |
| `runtime_files` | SHA256 of each file; root-owned, no group/world write, root-controlled ancestors | `runtime_changed`, `runtime_permissions` |
| `commands` | every `argv[0]` and every agent `executable` must appear in `runtime_files` | `runtime_unpinned` |
| `commands[].argv` | 1–64 entries, no NUL, absolute first element | `command_catalog` |
| `repositories` | a real `project_id`, a root-owned local mirror | `repository_read_failed` |

Compute the digests after the files are in place:

```bash
for f in /opt/nachtlabs-runtime/agent /opt/nachtlabs-runtime/python3 \
         /opt/nachtlabs-runtime/checks/development_agent.py; do
  printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
done
```

The `agents` map must **exactly equal** the dictionary the broker builds from the database
(`stages.py:168`), or a job fails with `agent_catalog_changed`. Its fields are `id`,
`provider`, `executable`, `version`, `expected_version`, `profile_version`, `model`, `role`
(`broker.py:57-65`). Read the stored agent row and transcribe it; do not invent values.

Ownership is checked for the catalog and every path above it, so no component of the path
may be group- or world-writable.

## 5. Work the table

For each of the 15 rows in [executor-qualification.md](executor-qualification.md), record
the host, the exact command, and what you actually observed. A row you did not observe is
`NOT RUN`, not a pass.

The rows most likely to fail, and how to check them:

**Row 14 — cgroup/BPF filtering, including IPv6.** If `IPAddressDeny=any` does not prevent a
connection, nothing here is safe.
```bash
# Inside a job with network:false, and from a networked job to a non-permitted address.
# The first must fail, the second must be the only reachable one.
getent hosts example.com || echo "DNS must not resolve here"
```

**Row 3 — dynamic identities cannot read secrets.** Check from inside a job, then check
descendants afterwards:
```bash
cat /etc/nachtlabs/credentials/master-key 2>&1   # must be denied
ls /var/lib/nachtlabs-executor/                 # must be denied
```

**Row 7 — cancellation kills the whole cgroup.** Trigger an emergency stop from the
interface mid-job, then:
```bash
systemctl list-units 'nachtlabs-job-*'   # expect none left
```

**Row 13 — two brokers cannot execute at once.** Start a second broker by hand and confirm
it refuses rather than running concurrently.

## 6. Record the receipt

Only when every row has been observed, or the ones that have not are recorded as `NOT RUN`:

```bash
sudo python3 scripts/qualify-executor.py \
  --evidence /path/to/completed-report.md \
  --confirm-linux-isolation-passed
```

The report must be the **completed** one; the script rejects an unfilled template under 100
bytes. The receipt binds `catalog_sha256`, so **any later edit to the catalog invalidates
it** and requires requalification. The write uses `O_EXCL` and will not overwrite: to
requalify, deliberately remove the old receipt first.

## 7. Enable and smoke test

```bash
sudo systemctl enable --now nachtlabs-executor
systemctl status nachtlabs-executor
```

Bind an agent in the interface, then run a work request against the disposable project.
Watch the broker:

```bash
journalctl -u nachtlabs-executor -f
```

Verify the boundary tests, which are skipped unless explicitly opted in and require root
with the broker stopped:

```bash
sudo systemctl stop nachtlabs-executor
sudo NACHTLABS_NATIVE_ACCEPTANCE=1 uv run --no-sync pytest tests/native/test_executor_boundary.py -v
```

These cover selected boundaries, not the whole table.

## 8. When something goes wrong

A job that dies mid-flight leaves the run `uncertain` rather than silently retrying, because
a crashed process must not be replayed. Inspect, then reconcile locally:

```bash
sudo systemctl stop nachtlabs-executor
# Inspect cgroups, the workspace and any delivery journal, then:
sudo python3 scripts/reconcile-executor.py <job-id> \
  --reason "what you found and why this is the right resolution"
```

The tool requires root, a reason of at least ten characters, and
`--confirm-executor-stopped`. It takes the broker lock, so it cannot race a running broker.

On broker restart, `sandbox.recover()` stops any recorded cgroup and releases an orphaned
tmpfs workspace before the lease is released. If a mount is left behind, it refuses to
proceed rather than releasing into an unknown state.

## Rolling back

Stop the executor and remove the receipt. The unit will not start without it:

```bash
sudo systemctl disable --now nachtlabs-executor
sudo rm /etc/nachtlabs/executor-qualification.json
```

Candidates and delivery journals under `/var/lib/nachtlabs-executor` are **not** removed by
this. Pair the state with the database before you delete anything:

```bash
sudo systemctl stop nachtlabs-api nachtlabs-worker nachtlabs-executor
# mode is positional; --archive and --recipient are the operator's own choices.
sudo python3 scripts/snapshot.py backup --archive /var/backups/nachtlabs/paired.tar.age
# see docs/operations/backup-and-restore.md for the recipient and the paired procedure
```
